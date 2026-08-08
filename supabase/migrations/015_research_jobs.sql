-- =============================================================================
-- Durable research jobs for long-running backend work.
-- The browser can observe only its own jobs; creation, claiming and mutation
-- are restricted to the trusted backend service role.
-- =============================================================================

create table if not exists public.research_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid,
  paper_id uuid,
  job_type text not null,
  status text not null default 'pending',
  progress integer not null default 0,
  input jsonb not null default '{}'::jsonb,
  result jsonb not null default '{}'::jsonb,
  error_message text,
  attempts integer not null default 0,
  max_attempts integer not null default 3,
  available_at timestamp with time zone not null default now(),
  lease_owner text,
  lease_expires_at timestamp with time zone,
  started_at timestamp with time zone,
  completed_at timestamp with time zone,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint research_jobs_type_not_blank
    check (length(btrim(job_type)) between 1 and 100),
  constraint research_jobs_status_check
    check (status in ('pending', 'running', 'succeeded', 'failed', 'cancelled')),
  constraint research_jobs_progress_check
    check (progress between 0 and 100),
  constraint research_jobs_attempts_check
    check (attempts >= 0 and max_attempts between 1 and 10),
  constraint research_jobs_project_owner_fk
    foreign key (project_id, user_id)
    references public.research_projects(id, user_id)
    on delete set null (project_id),
  constraint research_jobs_paper_owner_fk
    foreign key (paper_id, user_id)
    references public.papers(id, user_id)
    on delete cascade
);

create index if not exists idx_research_jobs_claimable
  on public.research_jobs(status, available_at, created_at)
  where status in ('pending', 'running');

create index if not exists idx_research_jobs_user_created
  on public.research_jobs(user_id, created_at desc);

create index if not exists idx_research_jobs_project_created
  on public.research_jobs(user_id, project_id, created_at desc);

create index if not exists idx_research_jobs_project_owner
  on public.research_jobs(project_id, user_id);

create index if not exists idx_research_jobs_paper
  on public.research_jobs(paper_id, user_id);

drop trigger if exists set_research_jobs_updated_at
  on public.research_jobs;

create trigger set_research_jobs_updated_at
before update on public.research_jobs
for each row execute function public.set_updated_at();

alter table public.research_jobs enable row level security;

drop policy if exists research_jobs_select_own
  on public.research_jobs;
create policy research_jobs_select_own
on public.research_jobs
for select
to authenticated
using ((select auth.uid()) = user_id);

revoke all on table public.research_jobs from anon, authenticated;
grant select on table public.research_jobs to authenticated;
grant all on table public.research_jobs to service_role;

create or replace function public.claim_research_job(
  p_worker_id text,
  p_lease_seconds integer default 180
)
returns setof public.research_jobs
language plpgsql
set search_path = public
as $$
begin
  if p_worker_id is null or length(btrim(p_worker_id)) = 0 then
    raise exception 'worker id is required';
  end if;

  return query
  with candidate as (
    select job.id
    from public.research_jobs as job
    where job.attempts < job.max_attempts
      and (
        (job.status = 'pending' and job.available_at <= now())
        or (
          job.status = 'running'
          and job.lease_expires_at is not null
          and job.lease_expires_at <= now()
        )
      )
    order by job.available_at, job.created_at
    for update skip locked
    limit 1
  )
  update public.research_jobs as job
  set
    status = 'running',
    attempts = job.attempts + 1,
    lease_owner = p_worker_id,
    lease_expires_at = now() + make_interval(
      secs => least(greatest(p_lease_seconds, 30), 900)
    ),
    started_at = coalesce(job.started_at, now()),
    error_message = null
  from candidate
  where job.id = candidate.id
  returning job.*;
end;
$$;

revoke all on function public.claim_research_job(text, integer)
  from public, anon, authenticated;
grant execute on function public.claim_research_job(text, integer)
  to service_role;

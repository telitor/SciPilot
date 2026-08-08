-- =============================================================================
-- SciCopilot unified research projects.
-- Existing assets remain unassigned (project_id is nullable); no data backfill
-- or destructive delete behavior is introduced by this migration.
-- =============================================================================

create table if not exists public.research_projects (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  objective text,
  status text not null default 'active',
  current_stage text not null default 'discovery',
  metadata jsonb not null default '{}'::jsonb,
  archived_at timestamp with time zone,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint research_projects_name_not_blank
    check (length(btrim(name)) between 2 and 120),
  constraint research_projects_status_check
    check (status in ('draft', 'active', 'completed', 'archived')),
  constraint research_projects_stage_check
    check (
      current_stage in (
        'discovery',
        'literature',
        'question',
        'experiment',
        'reproduction',
        'analysis',
        'completed'
      )
    ),
  constraint research_projects_id_user_unique unique (id, user_id)
);

alter table public.papers
  add column if not exists project_id uuid;

alter table public.conversations
  add column if not exists project_id uuid;

alter table public.research_artifacts
  add column if not exists project_id uuid;

alter table public.activities
  add column if not exists project_id uuid;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'papers_project_owner_fk'
      and conrelid = 'public.papers'::regclass
  ) then
    alter table public.papers
      add constraint papers_project_owner_fk
      foreign key (project_id, user_id)
      references public.research_projects(id, user_id)
      on delete set null (project_id);
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'conversations_project_owner_fk'
      and conrelid = 'public.conversations'::regclass
  ) then
    alter table public.conversations
      add constraint conversations_project_owner_fk
      foreign key (project_id, user_id)
      references public.research_projects(id, user_id)
      on delete set null (project_id);
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'research_artifacts_project_owner_fk'
      and conrelid = 'public.research_artifacts'::regclass
  ) then
    alter table public.research_artifacts
      add constraint research_artifacts_project_owner_fk
      foreign key (project_id, user_id)
      references public.research_projects(id, user_id)
      on delete set null (project_id);
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'activities_project_owner_fk'
      and conrelid = 'public.activities'::regclass
  ) then
    alter table public.activities
      add constraint activities_project_owner_fk
      foreign key (project_id, user_id)
      references public.research_projects(id, user_id)
      on delete set null (project_id);
  end if;
end
$$;

create index if not exists idx_research_projects_user_status_updated
  on public.research_projects(user_id, status, updated_at desc);

create index if not exists idx_papers_user_project_updated
  on public.papers(user_id, project_id, updated_at desc);

create index if not exists idx_conversations_user_project_updated
  on public.conversations(user_id, project_id, updated_at desc);

create index if not exists idx_research_artifacts_user_project_updated
  on public.research_artifacts(user_id, project_id, updated_at desc);

create index if not exists idx_activities_user_project_created
  on public.activities(user_id, project_id, created_at desc);

drop trigger if exists set_research_projects_updated_at
  on public.research_projects;

create trigger set_research_projects_updated_at
before update on public.research_projects
for each row execute function public.set_updated_at();

alter table public.research_projects enable row level security;

drop policy if exists research_projects_select_own
  on public.research_projects;
create policy research_projects_select_own
on public.research_projects
for select
to authenticated
using ((select auth.uid()) = user_id);

drop policy if exists research_projects_insert_own
  on public.research_projects;
create policy research_projects_insert_own
on public.research_projects
for insert
to authenticated
with check ((select auth.uid()) = user_id);

drop policy if exists research_projects_update_own
  on public.research_projects;
create policy research_projects_update_own
on public.research_projects
for update
to authenticated
using ((select auth.uid()) = user_id)
with check ((select auth.uid()) = user_id);

revoke all on table public.research_projects from anon;
grant select, insert, update on table public.research_projects to authenticated;
revoke delete on table public.research_projects from authenticated;
grant all on table public.research_projects to service_role;

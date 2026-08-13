-- Add opt-in Docker execution while preserving every existing manual record.

alter table public.experiment_runs
  add column if not exists execution_job_id uuid,
  add column if not exists approved_at timestamp with time zone;

alter table public.experiment_runs
  drop constraint if exists experiment_runs_execution_mode_check;

alter table public.experiment_runs
  add constraint experiment_runs_execution_mode_check
    check (execution_mode in ('manual-evidence', 'sandboxed-docker'));

alter table public.experiment_runs
  drop constraint if exists experiment_runs_sandbox_approval_check;

alter table public.experiment_runs
  add constraint experiment_runs_sandbox_approval_check
    check (
      execution_mode = 'manual-evidence'
      or approved_at is not null
    );

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'experiment_runs_execution_job_owner_fk'
  ) then
    alter table public.experiment_runs
      add constraint experiment_runs_execution_job_owner_fk
      foreign key (execution_job_id, user_id)
      references public.research_jobs(id, user_id)
      on delete set null (execution_job_id);
  end if;
end
$$;

create unique index if not exists idx_experiment_runs_execution_job
  on public.experiment_runs(execution_job_id)
  where execution_job_id is not null;

create index if not exists idx_experiment_runs_execution_job_owner
  on public.experiment_runs(execution_job_id, user_id)
  where execution_job_id is not null;

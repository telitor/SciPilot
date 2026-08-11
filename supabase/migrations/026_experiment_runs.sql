-- Auditable experiment runs for the manual-evidence execution mode.
-- Third-party code is never executed by the API server in this phase.

create table if not exists public.experiment_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid,
  code_artifact_id uuid not null,
  result_artifact_id uuid,
  execution_mode text not null default 'manual-evidence',
  status text not null default 'planned',
  commit_sha text not null,
  command text not null,
  environment jsonb not null default '{}'::jsonb,
  notes text,
  exit_code integer,
  stdout_excerpt text,
  stderr_excerpt text,
  output_files jsonb not null default '[]'::jsonb,
  started_at timestamp with time zone,
  completed_at timestamp with time zone,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint experiment_runs_id_user_unique unique (id, user_id),
  constraint experiment_runs_project_owner_fk
    foreign key (project_id, user_id)
    references public.research_projects(id, user_id)
    on delete set null (project_id),
  constraint experiment_runs_code_artifact_owner_fk
    foreign key (code_artifact_id, user_id)
    references public.research_artifacts(id, user_id)
    on delete restrict,
  constraint experiment_runs_result_artifact_owner_fk
    foreign key (result_artifact_id, user_id)
    references public.research_artifacts(id, user_id)
    on delete set null (result_artifact_id),
  constraint experiment_runs_execution_mode_check
    check (execution_mode = 'manual-evidence'),
  constraint experiment_runs_status_check
    check (status in ('planned', 'running', 'succeeded', 'failed', 'cancelled')),
  constraint experiment_runs_commit_sha_check
    check (commit_sha ~ '^[0-9a-fA-F]{7,64}$'),
  constraint experiment_runs_command_length_check
    check (length(btrim(command)) between 1 and 4000),
  constraint experiment_runs_notes_length_check
    check (notes is null or length(notes) <= 4000),
  constraint experiment_runs_stdout_length_check
    check (stdout_excerpt is null or length(stdout_excerpt) <= 50000),
  constraint experiment_runs_stderr_length_check
    check (stderr_excerpt is null or length(stderr_excerpt) <= 50000),
  constraint experiment_runs_output_files_array_check
    check (jsonb_typeof(output_files) = 'array'),
  constraint experiment_runs_environment_object_check
    check (jsonb_typeof(environment) = 'object'),
  constraint experiment_runs_completion_shape_check
    check (
      (status in ('planned', 'running') and completed_at is null)
      or (status in ('succeeded', 'failed', 'cancelled') and completed_at is not null)
    ),
  constraint experiment_runs_success_exit_check
    check (status <> 'succeeded' or exit_code = 0)
);

create index if not exists idx_experiment_runs_user_created
  on public.experiment_runs(user_id, created_at desc);

create index if not exists idx_experiment_runs_project_created
  on public.experiment_runs(user_id, project_id, created_at desc)
  where project_id is not null;

create index if not exists idx_experiment_runs_project_owner
  on public.experiment_runs(project_id, user_id)
  where project_id is not null;

create index if not exists idx_experiment_runs_code_created
  on public.experiment_runs(user_id, code_artifact_id, created_at desc);

create index if not exists idx_experiment_runs_code_owner
  on public.experiment_runs(code_artifact_id, user_id);

create index if not exists idx_experiment_runs_result_artifact
  on public.experiment_runs(result_artifact_id)
  where result_artifact_id is not null;

create index if not exists idx_experiment_runs_result_owner
  on public.experiment_runs(result_artifact_id, user_id)
  where result_artifact_id is not null;

drop trigger if exists set_experiment_runs_updated_at
  on public.experiment_runs;
create trigger set_experiment_runs_updated_at
before update on public.experiment_runs
for each row execute function public.set_updated_at();

alter table public.experiment_runs enable row level security;

drop policy if exists experiment_runs_select_own
  on public.experiment_runs;
create policy experiment_runs_select_own
on public.experiment_runs
for select
to authenticated
using ((select auth.uid()) = user_id);

revoke all on table public.experiment_runs from anon, authenticated, service_role;
grant select on table public.experiment_runs to authenticated;
grant select, insert, update on table public.experiment_runs to service_role;

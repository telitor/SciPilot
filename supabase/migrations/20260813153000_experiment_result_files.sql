-- Persist small, analyzable outputs produced by approved Docker experiment runs.
-- Files remain private and are accessed only by the trusted FastAPI backend.

create table if not exists public.experiment_result_files (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid,
  experiment_run_id uuid not null,
  result_artifact_id uuid,
  file_name text not null,
  relative_path text not null,
  storage_path text not null,
  media_type text not null,
  size_bytes bigint not null,
  checksum_sha256 text not null,
  created_at timestamp with time zone not null default now(),
  constraint experiment_result_files_id_user_unique unique (id, user_id),
  constraint experiment_result_files_run_path_unique
    unique (experiment_run_id, relative_path),
  constraint experiment_result_files_project_owner_fk
    foreign key (project_id, user_id)
    references public.research_projects(id, user_id)
    on delete set null (project_id),
  constraint experiment_result_files_run_owner_fk
    foreign key (experiment_run_id, user_id)
    references public.experiment_runs(id, user_id)
    on delete restrict,
  constraint experiment_result_files_artifact_owner_fk
    foreign key (result_artifact_id, user_id)
    references public.research_artifacts(id, user_id)
    on delete set null (result_artifact_id),
  constraint experiment_result_files_name_check
    check (length(btrim(file_name)) between 1 and 255),
  constraint experiment_result_files_relative_path_check
    check (length(btrim(relative_path)) between 1 and 1024),
  constraint experiment_result_files_storage_path_check
    check (length(btrim(storage_path)) between 1 and 2048),
  constraint experiment_result_files_media_type_check
    check (media_type in (
      'text/csv',
      'application/json',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )),
  constraint experiment_result_files_size_check
    check (size_bytes between 1 and 5242880),
  constraint experiment_result_files_checksum_check
    check (checksum_sha256 ~ '^[0-9a-f]{64}$')
);

create index if not exists idx_experiment_result_files_user_created
  on public.experiment_result_files(user_id, created_at desc);

create index if not exists idx_experiment_result_files_run_owner
  on public.experiment_result_files(experiment_run_id, user_id);

create index if not exists idx_experiment_result_files_project_owner
  on public.experiment_result_files(project_id, user_id)
  where project_id is not null;

create index if not exists idx_experiment_result_files_artifact_owner
  on public.experiment_result_files(result_artifact_id, user_id)
  where result_artifact_id is not null;

alter table public.experiment_result_files enable row level security;

drop policy if exists experiment_result_files_select_own
  on public.experiment_result_files;
create policy experiment_result_files_select_own
on public.experiment_result_files
for select
to authenticated
using ((select auth.uid()) = user_id);

revoke all on table public.experiment_result_files
  from anon, authenticated, service_role;
grant select, insert, update on table public.experiment_result_files
  to service_role;

insert into storage.buckets (
  id,
  name,
  public,
  file_size_limit,
  allowed_mime_types
)
values (
  'experiment-results',
  'experiment-results',
  false,
  5242880,
  array[
    'text/csv',
    'application/json',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
  ]::text[]
)
on conflict (id) do update
set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

-- The browser never accesses this bucket. Service-role backend access bypasses
-- RLS, while the absence of authenticated storage policies keeps objects private.
drop policy if exists experiment_results_storage_select_own on storage.objects;
drop policy if exists experiment_results_storage_insert_own on storage.objects;
drop policy if exists experiment_results_storage_update_own on storage.objects;
drop policy if exists experiment_results_storage_delete_own on storage.objects;

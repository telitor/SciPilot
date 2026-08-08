-- =============================================================================
-- Map each user's paper to its file in the shared iFlytek ChatDoc repository.
-- The repository remains external; Supabase stores only ownership, identifiers
-- and synchronization state needed by the trusted FastAPI backend.
-- =============================================================================

create table if not exists public.paper_knowledge_files (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  paper_id uuid not null,
  provider text not null default 'xunfei-chatdoc',
  repository_id text not null,
  provider_file_id text,
  file_name text not null,
  checksum_sha256 text,
  status text not null default 'pending',
  error_message text,
  provider_sid text,
  attempt_count integer not null default 0,
  last_attempt_at timestamp with time zone,
  vectored_at timestamp with time zone,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint paper_knowledge_files_owner_fk
    foreign key (paper_id, user_id)
    references public.papers(id, user_id)
    on delete cascade,
  constraint paper_knowledge_files_paper_provider_unique
    unique (paper_id, provider),
  constraint paper_knowledge_files_status_check
    check (status in (
      'pending',
      'uploaded',
      'processing',
      'vectored',
      'failed'
    )),
  constraint paper_knowledge_files_attempt_count_check
    check (attempt_count >= 0)
);

create unique index if not exists paper_knowledge_files_provider_file_unique
on public.paper_knowledge_files(provider, provider_file_id)
where provider_file_id is not null;

create index if not exists paper_knowledge_files_user_updated
on public.paper_knowledge_files(user_id, updated_at desc);

create index if not exists paper_knowledge_files_status
on public.paper_knowledge_files(status, updated_at);

drop trigger if exists set_paper_knowledge_files_updated_at
on public.paper_knowledge_files;
create trigger set_paper_knowledge_files_updated_at
before update on public.paper_knowledge_files
for each row execute function public.set_updated_at();

alter table public.paper_knowledge_files enable row level security;

drop policy if exists paper_knowledge_files_select_own
on public.paper_knowledge_files;
create policy paper_knowledge_files_select_own
on public.paper_knowledge_files
for select
to authenticated
using ((select auth.uid()) is not null and (select auth.uid()) = user_id);

drop policy if exists paper_knowledge_files_insert_own
on public.paper_knowledge_files;
create policy paper_knowledge_files_insert_own
on public.paper_knowledge_files
for insert
to authenticated
with check ((select auth.uid()) is not null and (select auth.uid()) = user_id);

drop policy if exists paper_knowledge_files_update_own
on public.paper_knowledge_files;
create policy paper_knowledge_files_update_own
on public.paper_knowledge_files
for update
to authenticated
using ((select auth.uid()) is not null and (select auth.uid()) = user_id)
with check ((select auth.uid()) is not null and (select auth.uid()) = user_id);

drop policy if exists paper_knowledge_files_delete_own
on public.paper_knowledge_files;
create policy paper_knowledge_files_delete_own
on public.paper_knowledge_files
for delete
to authenticated
using ((select auth.uid()) is not null and (select auth.uid()) = user_id);

revoke all on table public.paper_knowledge_files from anon;
grant select, insert, update, delete
on table public.paper_knowledge_files
to authenticated, service_role;

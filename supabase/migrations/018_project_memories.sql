-- =============================================================================
-- Durable, source-aware project memory for professional research agents.
-- Memories are managed through the FastAPI backend; physical delete is disabled.
-- =============================================================================

create table if not exists public.project_memories (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid not null,
  memory_type text not null default 'fact',
  title text not null,
  content text not null,
  source_type text not null default 'manual',
  source_id uuid,
  source_version integer,
  status text not null default 'active',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint project_memories_project_owner_fk
    foreign key (project_id, user_id)
    references public.research_projects(id, user_id)
    on delete restrict,
  constraint project_memories_source_artifact_owner_fk
    foreign key (source_id, user_id)
    references public.research_artifacts(id, user_id)
    on delete restrict,
  constraint project_memories_type_check
    check (
      memory_type in (
        'fact',
        'decision',
        'constraint',
        'preference',
        'lesson',
        'artifact-summary'
      )
    ),
  constraint project_memories_source_type_check
    check (source_type in ('manual', 'artifact')),
  constraint project_memories_status_check
    check (status in ('active', 'archived')),
  constraint project_memories_title_not_blank
    check (length(btrim(title)) between 1 and 200),
  constraint project_memories_content_not_blank
    check (length(btrim(content)) between 1 and 8000),
  constraint project_memories_source_version_check
    check (source_version is null or source_version >= 1),
  constraint project_memories_source_shape_check
    check (
      (source_type = 'manual' and source_id is null and source_version is null)
      or
      (source_type = 'artifact' and source_id is not null and source_version is not null)
    )
);

create unique index if not exists idx_project_memories_artifact_source
  on public.project_memories(user_id, project_id, source_id)
  where source_type = 'artifact' and source_id is not null;

create index if not exists idx_project_memories_project_status_updated
  on public.project_memories(user_id, project_id, status, updated_at desc);

create index if not exists idx_project_memories_project_type_updated
  on public.project_memories(user_id, project_id, memory_type, updated_at desc);

create index if not exists idx_project_memories_source_owner
  on public.project_memories(source_id, user_id)
  where source_id is not null;

drop trigger if exists set_project_memories_updated_at
  on public.project_memories;

create trigger set_project_memories_updated_at
before update on public.project_memories
for each row execute function public.set_updated_at();

alter table public.project_memories enable row level security;

drop policy if exists project_memories_select_own
  on public.project_memories;
create policy project_memories_select_own
on public.project_memories
for select
to authenticated
using ((select auth.uid()) = user_id);

drop policy if exists project_memories_insert_own
  on public.project_memories;
create policy project_memories_insert_own
on public.project_memories
for insert
to authenticated
with check ((select auth.uid()) = user_id);

drop policy if exists project_memories_update_own
  on public.project_memories;
create policy project_memories_update_own
on public.project_memories
for update
to authenticated
using ((select auth.uid()) = user_id)
with check ((select auth.uid()) = user_id);

revoke all on table public.project_memories from anon, authenticated;
grant select, insert, update on table public.project_memories to service_role;

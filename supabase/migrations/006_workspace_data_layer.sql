-- =============================================================================
-- SciPilot workspace data layer
-- Extends the original chat schema with user profiles, paper workflows,
-- reusable research artifacts, an activity feed, a public catalog, a knowledge
-- graph, private PDF storage, indexes, triggers, and row-level security.
--
-- This migration is designed for Supabase Postgres and is safe to re-run.
-- =============================================================================

create extension if not exists pgcrypto;


-- -----------------------------------------------------------------------------
-- 1. Extend the original tables without breaking existing chat data.
-- -----------------------------------------------------------------------------

alter table public.profiles
  add column if not exists email text,
  add column if not exists bio text,
  add column if not exists preferences jsonb not null default '{}'::jsonb,
  add column if not exists updated_at timestamp with time zone not null default now();

alter table public.agents
  add column if not exists updated_at timestamp with time zone not null default now();

-- A conversation can be created before an agent is selected.
alter table public.conversations
  alter column agent_id drop not null;

alter table public.conversations
  add column if not exists module text not null default 'general',
  add column if not exists status text not null default 'active',
  add column if not exists context jsonb not null default '{}'::jsonb,
  add column if not exists metadata jsonb not null default '{}'::jsonb,
  add column if not exists archived_at timestamp with time zone;

alter table public.messages
  add column if not exists agent_id uuid references public.agents(id) on delete set null,
  add column if not exists parent_message_id uuid references public.messages(id) on delete set null,
  add column if not exists citations jsonb not null default '[]'::jsonb,
  add column if not exists metadata jsonb not null default '{}'::jsonb,
  add column if not exists model text,
  add column if not exists input_tokens integer,
  add column if not exists output_tokens integer,
  add column if not exists updated_at timestamp with time zone not null default now();

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'conversations_status_check'
      and conrelid = 'public.conversations'::regclass
  ) then
    alter table public.conversations
      add constraint conversations_status_check
      check (status in ('active', 'archived'));
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conname = 'messages_token_counts_check'
      and conrelid = 'public.messages'::regclass
  ) then
    alter table public.messages
      add constraint messages_token_counts_check
      check (
        (input_tokens is null or input_tokens >= 0)
        and (output_tokens is null or output_tokens >= 0)
      );
  end if;
end
$$;


-- -----------------------------------------------------------------------------
-- 2. Private user workspaces.
-- -----------------------------------------------------------------------------

create table if not exists public.papers (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null,
  authors text[] not null default '{}'::text[],
  abstract text,
  source_url text,
  arxiv_id text,
  doi text,
  file_path text,
  file_name text,
  mime_type text,
  file_size bigint,
  checksum_sha256 text,
  language text,
  publication_year integer,
  status text not null default 'uploading',
  is_favorite boolean not null default false,
  error_message text,
  metadata jsonb not null default '{}'::jsonb,
  uploaded_at timestamp with time zone not null default now(),
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint papers_status_check
    check (status in ('uploading', 'uploaded', 'processing', 'completed', 'error')),
  constraint papers_file_size_check
    check (file_size is null or file_size >= 0),
  constraint papers_publication_year_check
    check (
      publication_year is null
      or publication_year between 1000 and 2200
    ),
  constraint papers_id_user_unique
    unique (id, user_id)
);

create table if not exists public.paper_reports (
  id uuid primary key default gen_random_uuid(),
  paper_id uuid not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  report_type text not null default 'deep-read',
  status text not null default 'processing',
  summary text,
  sections jsonb not null default '[]'::jsonb,
  content jsonb not null default '{}'::jsonb,
  model text,
  error_message text,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint paper_reports_status_check
    check (status in ('pending', 'processing', 'completed', 'error')),
  constraint paper_reports_paper_owner_fk
    foreign key (paper_id, user_id)
    references public.papers(id, user_id)
    on delete cascade,
  constraint paper_reports_paper_type_unique
    unique (paper_id, report_type)
);

create table if not exists public.research_artifacts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  conversation_id uuid references public.conversations(id) on delete set null,
  paper_id uuid references public.papers(id) on delete set null,
  artifact_type text not null,
  title text not null,
  input jsonb not null default '{}'::jsonb,
  content jsonb not null default '{}'::jsonb,
  status text not null default 'completed',
  error_message text,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint research_artifacts_status_check
    check (status in ('pending', 'processing', 'completed', 'error'))
);

create table if not exists public.activities (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  module text not null,
  action text not null,
  target text not null,
  entity_type text,
  entity_id uuid,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamp with time zone not null default now()
);


-- -----------------------------------------------------------------------------
-- 3. Public research catalog and mixed public/private knowledge graph.
-- -----------------------------------------------------------------------------

create table if not exists public.catalog_resources (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  resource_type text not null,
  title text not null,
  description text,
  authors text[] not null default '{}'::text[],
  publication_year integer,
  source_name text not null,
  url text not null,
  external_id text,
  arxiv_id text,
  doi text,
  repository_url text,
  license text,
  topics text[] not null default '{}'::text[],
  metadata jsonb not null default '{}'::jsonb,
  is_featured boolean not null default false,
  is_public boolean not null default true,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint catalog_resources_publication_year_check
    check (
      publication_year is null
      or publication_year between 1000 and 2200
    )
);

create table if not exists public.knowledge_nodes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  resource_id uuid references public.catalog_resources(id) on delete set null,
  slug text not null,
  label text not null,
  category text not null,
  description text,
  metadata jsonb not null default '{}'::jsonb,
  is_public boolean not null default false,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now()
);

create table if not exists public.knowledge_edges (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  source_node_id uuid not null references public.knowledge_nodes(id) on delete cascade,
  target_node_id uuid not null references public.knowledge_nodes(id) on delete cascade,
  resource_id uuid references public.catalog_resources(id) on delete set null,
  relation text not null,
  strength numeric(4, 3) not null default 1.0,
  evidence text,
  metadata jsonb not null default '{}'::jsonb,
  is_public boolean not null default false,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint knowledge_edges_strength_check
    check (strength >= 0 and strength <= 1),
  constraint knowledge_edges_no_self_loop_check
    check (source_node_id <> target_node_id)
);

-- PostgreSQL treats NULLs as distinct in ordinary UNIQUE constraints. Partial
-- indexes give public nodes/edges a stable upsert target while still allowing
-- each user to maintain a private namespace.
create unique index if not exists idx_knowledge_nodes_public_slug_unique
on public.knowledge_nodes(slug)
where user_id is null;

create unique index if not exists idx_knowledge_nodes_private_slug_unique
on public.knowledge_nodes(user_id, slug)
where user_id is not null;

create unique index if not exists idx_knowledge_edges_public_unique
on public.knowledge_edges(source_node_id, target_node_id, relation)
where user_id is null;

create unique index if not exists idx_knowledge_edges_private_unique
on public.knowledge_edges(user_id, source_node_id, target_node_id, relation)
where user_id is not null;


-- -----------------------------------------------------------------------------
-- 4. Keep public.profiles synchronized with newly registered auth users.
-- -----------------------------------------------------------------------------

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  profile_username text;
  profile_role text;
begin
  profile_username := nullif(
    trim(
      coalesce(
        new.raw_user_meta_data ->> 'username',
        new.raw_user_meta_data ->> 'name',
        split_part(coalesce(new.email, ''), '@', 1)
      )
    ),
    ''
  );

  profile_role := case
    when new.raw_app_meta_data ->> 'role' = 'admin' then 'admin'
    else 'user'
  end;

  insert into public.profiles (
    id,
    email,
    username,
    role,
    created_at,
    updated_at
  )
  values (
    new.id,
    new.email,
    coalesce(profile_username, '研究者'),
    profile_role,
    coalesce(new.created_at, now()),
    now()
  )
  on conflict (id) do update
  set
    email = excluded.email,
    username = coalesce(public.profiles.username, excluded.username),
    updated_at = now();

  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;

create trigger on_auth_user_created
after insert on auth.users
for each row
execute function public.handle_new_user();

drop trigger if exists on_auth_user_email_updated on auth.users;

create trigger on_auth_user_email_updated
after update of email on auth.users
for each row
when (old.email is distinct from new.email)
execute function public.handle_new_user();

-- Backfill users that existed before this trigger was installed.
insert into public.profiles (
  id,
  email,
  username,
  role,
  created_at,
  updated_at
)
select
  users.id,
  users.email,
  coalesce(
    nullif(
      trim(
        coalesce(
          users.raw_user_meta_data ->> 'username',
          users.raw_user_meta_data ->> 'name',
          split_part(coalesce(users.email, ''), '@', 1)
        )
      ),
      ''
    ),
    '研究者'
  ),
  case
    when users.raw_app_meta_data ->> 'role' = 'admin' then 'admin'
    else 'user'
  end,
  coalesce(users.created_at, now()),
  now()
from auth.users as users
on conflict (id) do update
set email = excluded.email;


-- -----------------------------------------------------------------------------
-- 5. updated_at triggers.
-- -----------------------------------------------------------------------------

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_profiles_updated_at on public.profiles;
create trigger set_profiles_updated_at
before update on public.profiles
for each row execute function public.set_updated_at();

drop trigger if exists set_agents_updated_at on public.agents;
create trigger set_agents_updated_at
before update on public.agents
for each row execute function public.set_updated_at();

drop trigger if exists set_conversations_updated_at on public.conversations;
create trigger set_conversations_updated_at
before update on public.conversations
for each row execute function public.set_updated_at();

drop trigger if exists set_messages_updated_at on public.messages;
create trigger set_messages_updated_at
before update on public.messages
for each row execute function public.set_updated_at();

drop trigger if exists set_papers_updated_at on public.papers;
create trigger set_papers_updated_at
before update on public.papers
for each row execute function public.set_updated_at();

drop trigger if exists set_paper_reports_updated_at on public.paper_reports;
create trigger set_paper_reports_updated_at
before update on public.paper_reports
for each row execute function public.set_updated_at();

drop trigger if exists set_research_artifacts_updated_at on public.research_artifacts;
create trigger set_research_artifacts_updated_at
before update on public.research_artifacts
for each row execute function public.set_updated_at();

drop trigger if exists set_catalog_resources_updated_at on public.catalog_resources;
create trigger set_catalog_resources_updated_at
before update on public.catalog_resources
for each row execute function public.set_updated_at();

drop trigger if exists set_knowledge_nodes_updated_at on public.knowledge_nodes;
create trigger set_knowledge_nodes_updated_at
before update on public.knowledge_nodes
for each row execute function public.set_updated_at();

drop trigger if exists set_knowledge_edges_updated_at on public.knowledge_edges;
create trigger set_knowledge_edges_updated_at
before update on public.knowledge_edges
for each row execute function public.set_updated_at();


-- -----------------------------------------------------------------------------
-- 6. Query indexes.
-- -----------------------------------------------------------------------------

create index if not exists idx_profiles_email_lower
on public.profiles(lower(email))
where email is not null;

create index if not exists idx_agents_category_public
on public.agents(category, is_public);

create index if not exists idx_conversations_user_updated
on public.conversations(user_id, updated_at desc);

create index if not exists idx_conversations_user_module_updated
on public.conversations(user_id, module, updated_at desc);

create index if not exists idx_messages_conversation_created
on public.messages(conversation_id, created_at);

create index if not exists idx_messages_parent_message
on public.messages(parent_message_id)
where parent_message_id is not null;

create index if not exists idx_papers_user_created
on public.papers(user_id, created_at desc);

create index if not exists idx_papers_user_status
on public.papers(user_id, status);

create index if not exists idx_papers_user_favorite
on public.papers(user_id, updated_at desc)
where is_favorite = true;

create index if not exists idx_papers_user_arxiv
on public.papers(user_id, arxiv_id)
where arxiv_id is not null;

create unique index if not exists idx_papers_user_file_path_unique
on public.papers(user_id, file_path)
where file_path is not null;

create index if not exists idx_paper_reports_user_updated
on public.paper_reports(user_id, updated_at desc);

create index if not exists idx_paper_reports_paper
on public.paper_reports(paper_id);

create index if not exists idx_research_artifacts_user_type_updated
on public.research_artifacts(user_id, artifact_type, updated_at desc);

create index if not exists idx_research_artifacts_conversation
on public.research_artifacts(conversation_id)
where conversation_id is not null;

create index if not exists idx_activities_user_created
on public.activities(user_id, created_at desc);

create index if not exists idx_activities_user_module_created
on public.activities(user_id, module, created_at desc);

create index if not exists idx_catalog_resources_type_public
on public.catalog_resources(resource_type, is_public);

create index if not exists idx_catalog_resources_featured
on public.catalog_resources(is_featured, resource_type)
where is_public = true;

create index if not exists idx_catalog_resources_arxiv
on public.catalog_resources(arxiv_id)
where arxiv_id is not null;

create index if not exists idx_catalog_resources_external_id
on public.catalog_resources(external_id)
where external_id is not null;

create index if not exists idx_catalog_resources_topics
on public.catalog_resources using gin(topics);

create index if not exists idx_knowledge_nodes_category_public
on public.knowledge_nodes(category, is_public);

create index if not exists idx_knowledge_nodes_resource
on public.knowledge_nodes(resource_id)
where resource_id is not null;

create index if not exists idx_knowledge_edges_source
on public.knowledge_edges(source_node_id);

create index if not exists idx_knowledge_edges_target
on public.knowledge_edges(target_node_id);

create index if not exists idx_knowledge_edges_relation_public
on public.knowledge_edges(relation, is_public);


-- -----------------------------------------------------------------------------
-- 7. Row-level security.
-- -----------------------------------------------------------------------------

alter table public.papers enable row level security;
alter table public.paper_reports enable row level security;
alter table public.research_artifacts enable row level security;
alter table public.activities enable row level security;
alter table public.catalog_resources enable row level security;
alter table public.knowledge_nodes enable row level security;
alter table public.knowledge_edges enable row level security;

-- The earlier migration did not include message update/delete policies.
drop policy if exists messages_update_own on public.messages;
create policy messages_update_own
on public.messages
for update
to authenticated
using (
  auth.uid() = user_id
  and exists (
    select 1
    from public.conversations as conversation
    where conversation.id = messages.conversation_id
      and conversation.user_id = auth.uid()
  )
)
with check (
  auth.uid() = user_id
  and exists (
    select 1
    from public.conversations as conversation
    where conversation.id = messages.conversation_id
      and conversation.user_id = auth.uid()
  )
);

drop policy if exists messages_delete_own on public.messages;
create policy messages_delete_own
on public.messages
for delete
to authenticated
using (
  auth.uid() = user_id
  and exists (
    select 1
    from public.conversations as conversation
    where conversation.id = messages.conversation_id
      and conversation.user_id = auth.uid()
  )
);

drop policy if exists papers_select_own on public.papers;
create policy papers_select_own
on public.papers
for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists papers_insert_own on public.papers;
create policy papers_insert_own
on public.papers
for insert
to authenticated
with check (auth.uid() = user_id);

drop policy if exists papers_update_own on public.papers;
create policy papers_update_own
on public.papers
for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists papers_delete_own on public.papers;
create policy papers_delete_own
on public.papers
for delete
to authenticated
using (auth.uid() = user_id);

drop policy if exists paper_reports_select_own on public.paper_reports;
create policy paper_reports_select_own
on public.paper_reports
for select
to authenticated
using (
  auth.uid() = user_id
  and exists (
    select 1
    from public.papers as paper
    where paper.id = paper_reports.paper_id
      and paper.user_id = auth.uid()
  )
);

drop policy if exists paper_reports_insert_own on public.paper_reports;
create policy paper_reports_insert_own
on public.paper_reports
for insert
to authenticated
with check (
  auth.uid() = user_id
  and exists (
    select 1
    from public.papers as paper
    where paper.id = paper_reports.paper_id
      and paper.user_id = auth.uid()
  )
);

drop policy if exists paper_reports_update_own on public.paper_reports;
create policy paper_reports_update_own
on public.paper_reports
for update
to authenticated
using (
  auth.uid() = user_id
  and exists (
    select 1
    from public.papers as paper
    where paper.id = paper_reports.paper_id
      and paper.user_id = auth.uid()
  )
)
with check (
  auth.uid() = user_id
  and exists (
    select 1
    from public.papers as paper
    where paper.id = paper_reports.paper_id
      and paper.user_id = auth.uid()
  )
);

drop policy if exists paper_reports_delete_own on public.paper_reports;
create policy paper_reports_delete_own
on public.paper_reports
for delete
to authenticated
using (
  auth.uid() = user_id
  and exists (
    select 1
    from public.papers as paper
    where paper.id = paper_reports.paper_id
      and paper.user_id = auth.uid()
  )
);

drop policy if exists research_artifacts_select_own on public.research_artifacts;
create policy research_artifacts_select_own
on public.research_artifacts
for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists research_artifacts_insert_own on public.research_artifacts;
create policy research_artifacts_insert_own
on public.research_artifacts
for insert
to authenticated
with check (
  auth.uid() = user_id
  and (
    conversation_id is null
    or exists (
      select 1
      from public.conversations as conversation
      where conversation.id = research_artifacts.conversation_id
        and conversation.user_id = auth.uid()
    )
  )
  and (
    paper_id is null
    or exists (
      select 1
      from public.papers as paper
      where paper.id = research_artifacts.paper_id
        and paper.user_id = auth.uid()
    )
  )
);

drop policy if exists research_artifacts_update_own on public.research_artifacts;
create policy research_artifacts_update_own
on public.research_artifacts
for update
to authenticated
using (auth.uid() = user_id)
with check (
  auth.uid() = user_id
  and (
    conversation_id is null
    or exists (
      select 1
      from public.conversations as conversation
      where conversation.id = research_artifacts.conversation_id
        and conversation.user_id = auth.uid()
    )
  )
  and (
    paper_id is null
    or exists (
      select 1
      from public.papers as paper
      where paper.id = research_artifacts.paper_id
        and paper.user_id = auth.uid()
    )
  )
);

drop policy if exists research_artifacts_delete_own on public.research_artifacts;
create policy research_artifacts_delete_own
on public.research_artifacts
for delete
to authenticated
using (auth.uid() = user_id);

drop policy if exists activities_select_own on public.activities;
create policy activities_select_own
on public.activities
for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists activities_insert_own on public.activities;
create policy activities_insert_own
on public.activities
for insert
to authenticated
with check (auth.uid() = user_id);

drop policy if exists catalog_resources_select_public on public.catalog_resources;
create policy catalog_resources_select_public
on public.catalog_resources
for select
to anon, authenticated
using (is_public = true);

drop policy if exists knowledge_nodes_select_visible on public.knowledge_nodes;
create policy knowledge_nodes_select_visible
on public.knowledge_nodes
for select
to anon, authenticated
using (is_public = true or auth.uid() = user_id);

drop policy if exists knowledge_nodes_insert_own on public.knowledge_nodes;
create policy knowledge_nodes_insert_own
on public.knowledge_nodes
for insert
to authenticated
with check (
  auth.uid() = user_id
  and is_public = false
);

drop policy if exists knowledge_nodes_update_own on public.knowledge_nodes;
create policy knowledge_nodes_update_own
on public.knowledge_nodes
for update
to authenticated
using (auth.uid() = user_id)
with check (
  auth.uid() = user_id
  and is_public = false
);

drop policy if exists knowledge_nodes_delete_own on public.knowledge_nodes;
create policy knowledge_nodes_delete_own
on public.knowledge_nodes
for delete
to authenticated
using (auth.uid() = user_id);

drop policy if exists knowledge_edges_select_visible on public.knowledge_edges;
create policy knowledge_edges_select_visible
on public.knowledge_edges
for select
to anon, authenticated
using (is_public = true or auth.uid() = user_id);

drop policy if exists knowledge_edges_insert_own on public.knowledge_edges;
create policy knowledge_edges_insert_own
on public.knowledge_edges
for insert
to authenticated
with check (
  auth.uid() = user_id
  and is_public = false
  and exists (
    select 1
    from public.knowledge_nodes as source_node
    where source_node.id = knowledge_edges.source_node_id
      and (
        source_node.is_public = true
        or source_node.user_id = auth.uid()
      )
  )
  and exists (
    select 1
    from public.knowledge_nodes as target_node
    where target_node.id = knowledge_edges.target_node_id
      and (
        target_node.is_public = true
        or target_node.user_id = auth.uid()
      )
  )
);

drop policy if exists knowledge_edges_update_own on public.knowledge_edges;
create policy knowledge_edges_update_own
on public.knowledge_edges
for update
to authenticated
using (auth.uid() = user_id)
with check (
  auth.uid() = user_id
  and is_public = false
);

drop policy if exists knowledge_edges_delete_own on public.knowledge_edges;
create policy knowledge_edges_delete_own
on public.knowledge_edges
for delete
to authenticated
using (auth.uid() = user_id);


-- -----------------------------------------------------------------------------
-- 8. API grants. RLS remains the final authorization boundary.
-- -----------------------------------------------------------------------------

grant usage on schema public to anon, authenticated;

grant select
on public.agents, public.catalog_resources, public.knowledge_nodes, public.knowledge_edges
to anon, authenticated;

grant select, insert, update, delete
on public.conversations,
   public.messages,
   public.papers,
   public.paper_reports,
   public.research_artifacts,
   public.knowledge_nodes,
   public.knowledge_edges
to authenticated;

grant select, insert
on public.activities
to authenticated;

-- Prevent a browser client from changing its own role to admin.
revoke all on public.profiles from anon;
revoke insert, update, delete on public.profiles from authenticated;
grant select on public.profiles to authenticated;
grant insert (id, email, username, avatar_url, bio, preferences)
on public.profiles to authenticated;
grant update (username, avatar_url, bio, preferences)
on public.profiles to authenticated;

grant all
on public.profiles,
   public.agents,
   public.conversations,
   public.messages,
   public.papers,
   public.paper_reports,
   public.research_artifacts,
   public.activities,
   public.catalog_resources,
   public.knowledge_nodes,
   public.knowledge_edges
to service_role;


-- -----------------------------------------------------------------------------
-- 9. Private Supabase Storage bucket for uploaded PDFs.
--
-- Object paths must be: <auth-user-uuid>/<paper-uuid>/<original-file-name>
-- -----------------------------------------------------------------------------

insert into storage.buckets (
  id,
  name,
  public,
  file_size_limit,
  allowed_mime_types
)
values (
  'papers',
  'papers',
  false,
  26214400,
  array['application/pdf']::text[]
)
on conflict (id) do update
set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists papers_storage_select_own on storage.objects;
create policy papers_storage_select_own
on storage.objects
for select
to authenticated
using (
  bucket_id = 'papers'
  and (storage.foldername(name))[1] = auth.uid()::text
);

drop policy if exists papers_storage_insert_own on storage.objects;
create policy papers_storage_insert_own
on storage.objects
for insert
to authenticated
with check (
  bucket_id = 'papers'
  and (storage.foldername(name))[1] = auth.uid()::text
);

drop policy if exists papers_storage_update_own on storage.objects;
create policy papers_storage_update_own
on storage.objects
for update
to authenticated
using (
  bucket_id = 'papers'
  and (storage.foldername(name))[1] = auth.uid()::text
)
with check (
  bucket_id = 'papers'
  and (storage.foldername(name))[1] = auth.uid()::text
);

drop policy if exists papers_storage_delete_own on storage.objects;
create policy papers_storage_delete_own
on storage.objects
for delete
to authenticated
using (
  bucket_id = 'papers'
  and (storage.foldername(name))[1] = auth.uid()::text
);

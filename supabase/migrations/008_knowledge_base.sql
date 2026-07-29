-- =============================================================================
-- SciPilot knowledge base (RAG) data layer
--
-- Adds collection, document, chunk, ingestion, retrieval, and citation storage.
-- Supports PostgreSQL full-text search and optional 1536-dimensional pgvector
-- embeddings. This is intentionally separate from the lightweight public
-- catalog / knowledge graph introduced by migrations 006 and 007.
--
-- Safe to re-run on a Supabase project after migrations 001-007.
-- No copyrighted full text is seeded by this migration.
-- =============================================================================

create schema if not exists extensions;
create extension if not exists pgcrypto;
create extension if not exists vector with schema extensions;
create extension if not exists pg_trgm with schema extensions;


-- -----------------------------------------------------------------------------
-- 1. Knowledge-base collections.
--
-- Every collection has an owner. A public collection is readable by everyone,
-- but only its owner can change it. The API additionally restricts creation of
-- public collections to administrators.
-- -----------------------------------------------------------------------------

create table if not exists public.kb_collections (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  description text,
  is_public boolean not null default false,
  document_count integer not null default 0,
  embedding_model text,
  embedding_dimensions integer not null default 1536,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint kb_collections_name_check
    check (char_length(trim(name)) between 1 and 120),
  constraint kb_collections_document_count_check
    check (document_count >= 0),
  constraint kb_collections_embedding_dimensions_check
    check (embedding_dimensions = 1536),
  constraint kb_collections_id_user_unique
    unique (id, user_id)
);

create unique index if not exists idx_kb_collections_user_name_unique
on public.kb_collections(user_id, lower(name));


-- -----------------------------------------------------------------------------
-- 2. Source documents and retrievable chunks.
--
-- user_id and collection_id are repeated on child rows so API filters remain
-- simple and so composite foreign keys guarantee that ownership cannot drift.
-- -----------------------------------------------------------------------------

create table if not exists public.kb_documents (
  id uuid primary key default gen_random_uuid(),
  collection_id uuid not null,
  user_id uuid not null,
  title text not null,
  source_type text not null default 'upload',
  source_url text,
  storage_path text,
  file_name text,
  mime_type text,
  file_size bigint,
  checksum text,
  language text,
  status text not null default 'processing',
  chunk_count integer not null default 0,
  character_count integer not null default 0,
  error_message text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint kb_documents_collection_owner_fk
    foreign key (collection_id, user_id)
    references public.kb_collections(id, user_id)
    on delete cascade,
  constraint kb_documents_title_check
    check (char_length(trim(title)) between 1 and 500),
  constraint kb_documents_source_type_check
    check (
      source_type in (
        'upload',
        'pdf',
        'text',
        'markdown',
        'url',
        'web',
        'note',
        'paper',
        'catalog',
        'api'
      )
    ),
  constraint kb_documents_status_check
    check (status in ('pending', 'processing', 'ready', 'failed', 'archived')),
  constraint kb_documents_file_size_check
    check (file_size is null or file_size >= 0),
  constraint kb_documents_chunk_count_check
    check (chunk_count >= 0),
  constraint kb_documents_character_count_check
    check (character_count >= 0),
  constraint kb_documents_checksum_check
    check (checksum is null or checksum ~ '^[0-9a-fA-F]{64}$'),
  constraint kb_documents_id_owner_collection_unique
    unique (id, user_id, collection_id)
);

create unique index if not exists idx_kb_documents_collection_checksum_unique
on public.kb_documents(collection_id, checksum)
where checksum is not null and status <> 'failed';

create unique index if not exists idx_kb_documents_storage_path_unique
on public.kb_documents(storage_path)
where storage_path is not null;

create table if not exists public.kb_chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null,
  collection_id uuid not null,
  user_id uuid not null,
  chunk_index integer not null,
  title text,
  content text not null,
  token_count integer,
  embedding extensions.vector(1536),
  metadata jsonb not null default '{}'::jsonb,
  search_vector tsvector generated always as (
    to_tsvector(
      'simple',
      coalesce(title, '') || ' ' || coalesce(content, '')
    )
  ) stored,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint kb_chunks_document_owner_collection_fk
    foreign key (document_id, user_id, collection_id)
    references public.kb_documents(id, user_id, collection_id)
    on delete cascade,
  constraint kb_chunks_index_check
    check (chunk_index >= 0),
  constraint kb_chunks_content_check
    check (char_length(trim(content)) > 0),
  constraint kb_chunks_token_count_check
    check (token_count is null or token_count >= 0),
  constraint kb_chunks_document_index_unique
    unique (document_id, chunk_index)
);


-- -----------------------------------------------------------------------------
-- 3. Ingestion jobs.
--
-- These rows allow asynchronous OCR, parsing, chunking, and embedding workers
-- to report progress without overloading the document metadata field.
-- -----------------------------------------------------------------------------

create table if not exists public.kb_ingestion_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  collection_id uuid not null references public.kb_collections(id) on delete cascade,
  document_id uuid references public.kb_documents(id) on delete set null,
  source_type text not null default 'upload',
  status text not null default 'queued',
  stage text not null default 'queued',
  progress smallint not null default 0,
  attempt_count integer not null default 0,
  error_message text,
  metadata jsonb not null default '{}'::jsonb,
  started_at timestamp with time zone,
  completed_at timestamp with time zone,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint kb_ingestion_jobs_status_check
    check (status in ('queued', 'processing', 'completed', 'failed', 'canceled')),
  constraint kb_ingestion_jobs_progress_check
    check (progress between 0 and 100),
  constraint kb_ingestion_jobs_attempt_count_check
    check (attempt_count >= 0),
  constraint kb_ingestion_jobs_collection_owner_check
    foreign key (collection_id, user_id)
    references public.kb_collections(id, user_id)
    on delete cascade
);


-- -----------------------------------------------------------------------------
-- 4. Retrieval and citation audit trail.
--
-- kb_retrievals stores one search / grounded-answer event. kb_citations stores
-- the ranked source snapshots used by that event, so attribution remains
-- reviewable even if a source document is later removed.
-- -----------------------------------------------------------------------------

create table if not exists public.kb_retrievals (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  collection_id uuid references public.kb_collections(id) on delete set null,
  conversation_id uuid references public.conversations(id) on delete set null,
  message_id uuid references public.messages(id) on delete set null,
  query_text text not null,
  answer_text text,
  retrieval_mode text not null default 'full-text',
  model text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamp with time zone not null default now(),
  constraint kb_retrievals_query_check
    check (char_length(trim(query_text)) > 0),
  constraint kb_retrievals_mode_check
    check (retrieval_mode in ('full-text', 'vector', 'hybrid')),
  constraint kb_retrievals_id_user_unique
    unique (id, user_id)
);

create table if not exists public.kb_citations (
  id uuid primary key default gen_random_uuid(),
  retrieval_id uuid not null,
  user_id uuid not null,
  chunk_id uuid references public.kb_chunks(id) on delete set null,
  document_id uuid references public.kb_documents(id) on delete set null,
  rank integer not null,
  score double precision,
  document_title text,
  source_url text,
  file_name text,
  excerpt text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamp with time zone not null default now(),
  constraint kb_citations_retrieval_owner_fk
    foreign key (retrieval_id, user_id)
    references public.kb_retrievals(id, user_id)
    on delete cascade,
  constraint kb_citations_rank_check
    check (rank >= 1),
  constraint kb_citations_retrieval_rank_unique
    unique (retrieval_id, rank)
);


-- -----------------------------------------------------------------------------
-- 5. Timestamps and exact denormalized counts.
-- -----------------------------------------------------------------------------

drop trigger if exists set_kb_collections_updated_at on public.kb_collections;
create trigger set_kb_collections_updated_at
before update on public.kb_collections
for each row execute function public.set_updated_at();

drop trigger if exists set_kb_documents_updated_at on public.kb_documents;
create trigger set_kb_documents_updated_at
before update on public.kb_documents
for each row execute function public.set_updated_at();

drop trigger if exists set_kb_chunks_updated_at on public.kb_chunks;
create trigger set_kb_chunks_updated_at
before update on public.kb_chunks
for each row execute function public.set_updated_at();

drop trigger if exists set_kb_ingestion_jobs_updated_at on public.kb_ingestion_jobs;
create trigger set_kb_ingestion_jobs_updated_at
before update on public.kb_ingestion_jobs
for each row execute function public.set_updated_at();

create or replace function public.sync_kb_collection_document_count()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    update public.kb_collections
    set document_count = document_count + 1
    where id = new.collection_id;
    return new;
  end if;

  if tg_op = 'DELETE' then
    update public.kb_collections
    set document_count = greatest(document_count - 1, 0)
    where id = old.collection_id;
    return old;
  end if;

  if old.collection_id is distinct from new.collection_id then
    update public.kb_collections
    set document_count = greatest(document_count - 1, 0)
    where id = old.collection_id;

    update public.kb_collections
    set document_count = document_count + 1
    where id = new.collection_id;
  end if;

  return new;
end;
$$;

drop trigger if exists sync_kb_collection_document_count on public.kb_documents;
create trigger sync_kb_collection_document_count
after insert or delete or update of collection_id on public.kb_documents
for each row execute function public.sync_kb_collection_document_count();

create or replace function public.sync_kb_document_chunk_count()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    update public.kb_documents
    set chunk_count = chunk_count + 1
    where id = new.document_id;
    return new;
  end if;

  if tg_op = 'DELETE' then
    update public.kb_documents
    set chunk_count = greatest(chunk_count - 1, 0)
    where id = old.document_id;
    return old;
  end if;

  if old.document_id is distinct from new.document_id then
    update public.kb_documents
    set chunk_count = greatest(chunk_count - 1, 0)
    where id = old.document_id;

    update public.kb_documents
    set chunk_count = chunk_count + 1
    where id = new.document_id;
  end if;

  return new;
end;
$$;

drop trigger if exists sync_kb_document_chunk_count on public.kb_chunks;
create trigger sync_kb_document_chunk_count
after insert or delete or update of document_id on public.kb_chunks
for each row execute function public.sync_kb_document_chunk_count();

-- Re-running the migration also repairs any count drift from bulk imports.
update public.kb_collections as collection
set document_count = (
  select count(*)::integer
  from public.kb_documents as document
  where document.collection_id = collection.id
);

update public.kb_documents as document
set chunk_count = (
  select count(*)::integer
  from public.kb_chunks as chunk
  where chunk.document_id = document.id
);


-- -----------------------------------------------------------------------------
-- 6. Query indexes.
-- -----------------------------------------------------------------------------

create index if not exists idx_kb_collections_user_updated
on public.kb_collections(user_id, updated_at desc);

create index if not exists idx_kb_collections_public_updated
on public.kb_collections(updated_at desc)
where is_public = true;

create index if not exists idx_kb_documents_user_updated
on public.kb_documents(user_id, updated_at desc);

create index if not exists idx_kb_documents_collection_status_updated
on public.kb_documents(collection_id, status, updated_at desc);

create index if not exists idx_kb_chunks_document_order
on public.kb_chunks(document_id, chunk_index);

create index if not exists idx_kb_chunks_collection
on public.kb_chunks(collection_id);

create index if not exists idx_kb_chunks_search_vector
on public.kb_chunks using gin(search_vector);

create index if not exists idx_kb_chunks_title_trgm
on public.kb_chunks
using gin (title extensions.gin_trgm_ops);

create index if not exists idx_kb_chunks_content_trgm
on public.kb_chunks
using gin (content extensions.gin_trgm_ops);

create index if not exists idx_kb_chunks_embedding_hnsw
on public.kb_chunks
using hnsw (embedding extensions.vector_cosine_ops)
where embedding is not null;

create index if not exists idx_kb_ingestion_jobs_user_status_created
on public.kb_ingestion_jobs(user_id, status, created_at desc);

create index if not exists idx_kb_ingestion_jobs_document
on public.kb_ingestion_jobs(document_id)
where document_id is not null;

create index if not exists idx_kb_retrievals_user_created
on public.kb_retrievals(user_id, created_at desc);

create index if not exists idx_kb_retrievals_conversation
on public.kb_retrievals(conversation_id, created_at)
where conversation_id is not null;

create index if not exists idx_kb_citations_retrieval_rank
on public.kb_citations(retrieval_id, rank);

create index if not exists idx_kb_citations_document
on public.kb_citations(document_id)
where document_id is not null;


-- -----------------------------------------------------------------------------
-- 7. Row-level security.
-- -----------------------------------------------------------------------------

alter table public.kb_collections enable row level security;
alter table public.kb_documents enable row level security;
alter table public.kb_chunks enable row level security;
alter table public.kb_ingestion_jobs enable row level security;
alter table public.kb_retrievals enable row level security;
alter table public.kb_citations enable row level security;

-- Migration 006 already protected edge ownership, but its UPDATE policy did not
-- re-check whether replacement source/target nodes were visible to the owner.
-- Recreate it here so an authenticated client cannot attach an edge to another
-- user's private node by guessing its UUID.
drop policy if exists knowledge_edges_update_own on public.knowledge_edges;
create policy knowledge_edges_update_own
on public.knowledge_edges
for update
to authenticated
using (auth.uid() = user_id)
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

drop policy if exists kb_collections_select_visible on public.kb_collections;
create policy kb_collections_select_visible
on public.kb_collections
for select
to anon, authenticated
using (is_public = true or auth.uid() = user_id);

drop policy if exists kb_collections_insert_own on public.kb_collections;
create policy kb_collections_insert_own
on public.kb_collections
for insert
to authenticated
with check (
  auth.uid() = user_id
  and (
    is_public = false
    or exists (
      select 1
      from public.profiles as profile
      where profile.id = auth.uid()
        and profile.role = 'admin'
    )
  )
);

drop policy if exists kb_collections_update_own on public.kb_collections;
create policy kb_collections_update_own
on public.kb_collections
for update
to authenticated
using (auth.uid() = user_id)
with check (
  auth.uid() = user_id
  and (
    is_public = false
    or exists (
      select 1
      from public.profiles as profile
      where profile.id = auth.uid()
        and profile.role = 'admin'
    )
  )
);

drop policy if exists kb_collections_delete_own on public.kb_collections;
create policy kb_collections_delete_own
on public.kb_collections
for delete
to authenticated
using (auth.uid() = user_id);

drop policy if exists kb_documents_select_visible on public.kb_documents;
create policy kb_documents_select_visible
on public.kb_documents
for select
to anon, authenticated
using (
  auth.uid() = user_id
  or exists (
    select 1
    from public.kb_collections as collection
    where collection.id = kb_documents.collection_id
      and collection.is_public = true
  )
);

drop policy if exists kb_documents_insert_own on public.kb_documents;
create policy kb_documents_insert_own
on public.kb_documents
for insert
to authenticated
with check (
  auth.uid() = user_id
  and exists (
    select 1
    from public.kb_collections as collection
    where collection.id = kb_documents.collection_id
      and collection.user_id = auth.uid()
  )
);

drop policy if exists kb_documents_update_own on public.kb_documents;
create policy kb_documents_update_own
on public.kb_documents
for update
to authenticated
using (auth.uid() = user_id)
with check (
  auth.uid() = user_id
  and exists (
    select 1
    from public.kb_collections as collection
    where collection.id = kb_documents.collection_id
      and collection.user_id = auth.uid()
  )
);

drop policy if exists kb_documents_delete_own on public.kb_documents;
create policy kb_documents_delete_own
on public.kb_documents
for delete
to authenticated
using (auth.uid() = user_id);

drop policy if exists kb_chunks_select_visible on public.kb_chunks;
create policy kb_chunks_select_visible
on public.kb_chunks
for select
to anon, authenticated
using (
  auth.uid() = user_id
  or exists (
    select 1
    from public.kb_collections as collection
    where collection.id = kb_chunks.collection_id
      and collection.is_public = true
  )
);

drop policy if exists kb_chunks_insert_own on public.kb_chunks;
create policy kb_chunks_insert_own
on public.kb_chunks
for insert
to authenticated
with check (
  auth.uid() = user_id
  and exists (
    select 1
    from public.kb_documents as document
    where document.id = kb_chunks.document_id
      and document.collection_id = kb_chunks.collection_id
      and document.user_id = auth.uid()
  )
);

drop policy if exists kb_chunks_update_own on public.kb_chunks;
create policy kb_chunks_update_own
on public.kb_chunks
for update
to authenticated
using (auth.uid() = user_id)
with check (
  auth.uid() = user_id
  and exists (
    select 1
    from public.kb_documents as document
    where document.id = kb_chunks.document_id
      and document.collection_id = kb_chunks.collection_id
      and document.user_id = auth.uid()
  )
);

drop policy if exists kb_chunks_delete_own on public.kb_chunks;
create policy kb_chunks_delete_own
on public.kb_chunks
for delete
to authenticated
using (auth.uid() = user_id);

drop policy if exists kb_ingestion_jobs_select_own on public.kb_ingestion_jobs;
create policy kb_ingestion_jobs_select_own
on public.kb_ingestion_jobs
for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists kb_ingestion_jobs_insert_own on public.kb_ingestion_jobs;
create policy kb_ingestion_jobs_insert_own
on public.kb_ingestion_jobs
for insert
to authenticated
with check (
  auth.uid() = user_id
  and exists (
    select 1
    from public.kb_collections as collection
    where collection.id = kb_ingestion_jobs.collection_id
      and collection.user_id = auth.uid()
  )
  and (
    document_id is null
    or exists (
      select 1
      from public.kb_documents as document
      where document.id = kb_ingestion_jobs.document_id
        and document.collection_id = kb_ingestion_jobs.collection_id
        and document.user_id = auth.uid()
    )
  )
);

drop policy if exists kb_ingestion_jobs_update_own on public.kb_ingestion_jobs;
create policy kb_ingestion_jobs_update_own
on public.kb_ingestion_jobs
for update
to authenticated
using (auth.uid() = user_id)
with check (
  auth.uid() = user_id
  and exists (
    select 1
    from public.kb_collections as collection
    where collection.id = kb_ingestion_jobs.collection_id
      and collection.user_id = auth.uid()
  )
  and (
    document_id is null
    or exists (
      select 1
      from public.kb_documents as document
      where document.id = kb_ingestion_jobs.document_id
        and document.collection_id = kb_ingestion_jobs.collection_id
        and document.user_id = auth.uid()
    )
  )
);

drop policy if exists kb_ingestion_jobs_delete_own on public.kb_ingestion_jobs;
create policy kb_ingestion_jobs_delete_own
on public.kb_ingestion_jobs
for delete
to authenticated
using (auth.uid() = user_id);

drop policy if exists kb_retrievals_select_own on public.kb_retrievals;
create policy kb_retrievals_select_own
on public.kb_retrievals
for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists kb_retrievals_insert_own on public.kb_retrievals;
create policy kb_retrievals_insert_own
on public.kb_retrievals
for insert
to authenticated
with check (
  auth.uid() = user_id
  and (
    collection_id is null
    or exists (
      select 1
      from public.kb_collections as collection
      where collection.id = kb_retrievals.collection_id
        and (
          collection.is_public = true
          or collection.user_id = auth.uid()
        )
    )
  )
);

drop policy if exists kb_retrievals_update_own on public.kb_retrievals;
create policy kb_retrievals_update_own
on public.kb_retrievals
for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists kb_retrievals_delete_own on public.kb_retrievals;
create policy kb_retrievals_delete_own
on public.kb_retrievals
for delete
to authenticated
using (auth.uid() = user_id);

drop policy if exists kb_citations_select_own on public.kb_citations;
create policy kb_citations_select_own
on public.kb_citations
for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists kb_citations_insert_own on public.kb_citations;
create policy kb_citations_insert_own
on public.kb_citations
for insert
to authenticated
with check (
  auth.uid() = user_id
  and exists (
    select 1
    from public.kb_retrievals as retrieval
    where retrieval.id = kb_citations.retrieval_id
      and retrieval.user_id = auth.uid()
  )
  and (
    chunk_id is null
    or exists (
      select 1
      from public.kb_chunks as chunk
      join public.kb_collections as collection
        on collection.id = chunk.collection_id
      where chunk.id = kb_citations.chunk_id
        and (
          collection.is_public = true
          or collection.user_id = auth.uid()
        )
    )
  )
);

drop policy if exists kb_citations_update_own on public.kb_citations;
create policy kb_citations_update_own
on public.kb_citations
for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists kb_citations_delete_own on public.kb_citations;
create policy kb_citations_delete_own
on public.kb_citations
for delete
to authenticated
using (auth.uid() = user_id);


-- -----------------------------------------------------------------------------
-- 8. Hybrid knowledge-base search RPC.
--
-- Exact PostgREST parameter names are part of the backend contract:
--   query_text, query_embedding, match_count, filter_collection_id,
--   requesting_user_id
--
-- Only the service-role backend receives EXECUTE below. The caller-role check
-- is defense in depth in case a future migration broadens that grant.
-- -----------------------------------------------------------------------------

create or replace function public.search_knowledge_base(
  query_text text,
  query_embedding extensions.vector(1536),
  match_count integer,
  filter_collection_id uuid,
  requesting_user_id uuid
)
returns table (
  chunk_id uuid,
  document_id uuid,
  collection_id uuid,
  document_title text,
  source_type text,
  source_url text,
  file_name text,
  content text,
  chunk_index integer,
  metadata jsonb,
  score double precision
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  caller_role text := coalesce(auth.role(), 'anon');
  caller_user_id uuid := auth.uid();
  text_query tsquery := pg_catalog.plainto_tsquery(
    'simple',
    coalesce(query_text, '')
  );
  result_limit integer := least(greatest(coalesce(match_count, 8), 1), 50);
begin
  if caller_role <> 'service_role'
     and requesting_user_id is distinct from caller_user_id then
    raise exception 'requesting_user_id must match the authenticated user'
      using errcode = '42501';
  end if;

  return query
  with visible_chunks as (
    select
      chunk.id as chunk_id,
      chunk.document_id,
      chunk.collection_id,
      document.title as document_title,
      document.source_type,
      document.source_url,
      document.file_name,
      chunk.content,
      chunk.chunk_index,
      chunk.metadata,
      greatest(
        pg_catalog.ts_rank_cd(chunk.search_vector, text_query)::double precision,
        case
          when coalesce(trim(query_text), '') <> ''
           and pg_catalog.strpos(
             pg_catalog.lower(chunk.content),
             pg_catalog.lower(query_text)
           ) > 0
          then 0.30::double precision
          else 0.0::double precision
        end,
        case
          when coalesce(trim(query_text), '') <> '' then
            greatest(
              extensions.similarity(
                coalesce(chunk.title, ''),
                query_text
              )::double precision,
              extensions.similarity(
                chunk.content,
                query_text
              )::double precision
            )
          else 0.0::double precision
        end
      ) as text_score,
      case
        when query_embedding is not null and chunk.embedding is not null then
          greatest(
            0.0::double precision,
            1.0::double precision
              - (
                  chunk.embedding
                  operator(extensions.<=>)
                  query_embedding
                )::double precision
          )
        else 0.0::double precision
      end as vector_score
    from public.kb_chunks as chunk
    join public.kb_documents as document
      on document.id = chunk.document_id
    join public.kb_collections as collection
      on collection.id = chunk.collection_id
    where document.status = 'ready'
      and (
        collection.is_public = true
        or (
          requesting_user_id is not null
          and collection.user_id = requesting_user_id
        )
      )
      and (
        filter_collection_id is null
        or collection.id = filter_collection_id
      )
  ),
  scored_chunks as (
    select
      visible_chunks.chunk_id,
      visible_chunks.document_id,
      visible_chunks.collection_id,
      visible_chunks.document_title,
      visible_chunks.source_type,
      visible_chunks.source_url,
      visible_chunks.file_name,
      visible_chunks.content,
      visible_chunks.chunk_index,
      visible_chunks.metadata,
      case
        when query_embedding is null then
          visible_chunks.text_score
        when visible_chunks.text_score > 0 then
          (
            least(visible_chunks.text_score, 1.0::double precision) * 0.35
            + visible_chunks.vector_score * 0.65
          )
        else visible_chunks.vector_score
      end as score
    from visible_chunks
    where visible_chunks.text_score > 0
       or visible_chunks.vector_score > 0
  )
  select
    scored_chunks.chunk_id,
    scored_chunks.document_id,
    scored_chunks.collection_id,
    scored_chunks.document_title,
    scored_chunks.source_type,
    scored_chunks.source_url,
    scored_chunks.file_name,
    scored_chunks.content,
    scored_chunks.chunk_index,
    scored_chunks.metadata,
    scored_chunks.score
  from scored_chunks
  order by
    scored_chunks.score desc,
    scored_chunks.document_id,
    scored_chunks.chunk_index
  limit result_limit;
end;
$$;


-- -----------------------------------------------------------------------------
-- 9. API grants. RLS remains the authorization boundary for table access.
-- -----------------------------------------------------------------------------

grant usage on schema public to anon, authenticated;
grant usage on schema extensions to anon, authenticated, service_role;

grant select
on public.kb_collections,
   public.kb_documents,
   public.kb_chunks
to anon, authenticated;

grant insert, update, delete
on public.kb_collections,
   public.kb_documents,
   public.kb_chunks
to authenticated;

grant select, insert, update, delete
on public.kb_ingestion_jobs,
   public.kb_retrievals,
   public.kb_citations
to authenticated;

grant all
on public.kb_collections,
   public.kb_documents,
   public.kb_chunks,
   public.kb_ingestion_jobs,
   public.kb_retrievals,
   public.kb_citations
to service_role;

revoke all
on function public.search_knowledge_base(
  text,
  extensions.vector,
  integer,
  uuid,
  uuid
)
from public;

revoke all
on function public.search_knowledge_base(
  text,
  extensions.vector,
  integer,
  uuid,
  uuid
)
from anon, authenticated;

grant execute
on function public.search_knowledge_base(
  text,
  extensions.vector,
  integer,
  uuid,
  uuid
)
to service_role;


-- -----------------------------------------------------------------------------
-- 10. Private Supabase Storage bucket.
--
-- Object paths must be:
--   <auth-user-uuid>/<collection-uuid>/<generated-name>-<original-file-name>
--
-- Even documents in a public collection retain private raw files. Public users
-- receive searchable chunks and source metadata, not an unrestricted file URL.
-- -----------------------------------------------------------------------------

insert into storage.buckets (
  id,
  name,
  public,
  file_size_limit,
  allowed_mime_types
)
values (
  'knowledge-base',
  'knowledge-base',
  false,
  26214400,
  array[
    'application/pdf',
    'text/plain',
    'text/markdown',
    'text/x-markdown',
    'application/octet-stream'
  ]::text[]
)
on conflict (id) do update
set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists kb_storage_select_own on storage.objects;
create policy kb_storage_select_own
on storage.objects
for select
to authenticated
using (
  bucket_id = 'knowledge-base'
  and (storage.foldername(name))[1] = auth.uid()::text
);

drop policy if exists kb_storage_insert_own on storage.objects;
create policy kb_storage_insert_own
on storage.objects
for insert
to authenticated
with check (
  bucket_id = 'knowledge-base'
  and (storage.foldername(name))[1] = auth.uid()::text
);

drop policy if exists kb_storage_update_own on storage.objects;
create policy kb_storage_update_own
on storage.objects
for update
to authenticated
using (
  bucket_id = 'knowledge-base'
  and (storage.foldername(name))[1] = auth.uid()::text
)
with check (
  bucket_id = 'knowledge-base'
  and (storage.foldername(name))[1] = auth.uid()::text
);

drop policy if exists kb_storage_delete_own on storage.objects;
create policy kb_storage_delete_own
on storage.objects
for delete
to authenticated
using (
  bucket_id = 'knowledge-base'
  and (storage.foldername(name))[1] = auth.uid()::text
);

-- =============================================================================
-- Remove the legacy Supabase-hosted RAG knowledge base.
--
-- SciPilot now keeps knowledge-base files and vectors in iFlytek Spark ChatDoc.
-- This migration deliberately leaves the independent knowledge graph
-- (knowledge_nodes / knowledge_edges) and the "papers" Storage bucket intact.
-- It is safe to run whether or not the former 008 migration was applied.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. Preserve the knowledge-edge ownership hardening formerly shipped in 008.
--
-- The original migration 006 UPDATE policy checked only edge ownership.  The
-- replacement also prevents a user from re-pointing an owned edge at another
-- user's private node by guessing that node's UUID.
-- -----------------------------------------------------------------------------

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


-- -----------------------------------------------------------------------------
-- 2. Retire access policies for the former private Storage bucket.
--
-- Never delete stored objects in a schema migration.  The bucket metadata is
-- removed only when no object remains.  If objects still exist, an operator
-- can archive/delete them with service-role access and then remove the bucket.
-- -----------------------------------------------------------------------------

drop policy if exists kb_storage_select_own on storage.objects;
drop policy if exists kb_storage_insert_own on storage.objects;
drop policy if exists kb_storage_update_own on storage.objects;
drop policy if exists kb_storage_delete_own on storage.objects;

delete from storage.buckets as bucket
where bucket.id = 'knowledge-base'
  and not exists (
    select 1
    from storage.objects as stored_object
    where stored_object.bucket_id = bucket.id
  );

do $$
begin
  if exists (
    select 1
    from storage.buckets
    where id = 'knowledge-base'
  ) then
    raise notice
      'Storage bucket knowledge-base was retained because it still contains objects';
  end if;
end;
$$;


-- -----------------------------------------------------------------------------
-- 3. Drop the former relational RAG layer.
--
-- CASCADE removes each table's triggers, RLS policies, grants, indexes and
-- dependent constraints.  Child tables are listed first for clarity.
-- -----------------------------------------------------------------------------

drop table if exists public.kb_citations cascade;
drop table if exists public.kb_retrievals cascade;
drop table if exists public.kb_ingestion_jobs cascade;
drop table if exists public.kb_chunks cascade;
drop table if exists public.kb_documents cascade;
drop table if exists public.kb_collections cascade;


-- -----------------------------------------------------------------------------
-- 4. Remove legacy helper/RPC functions without assuming pgvector exists.
--
-- Looking functions up in the catalog avoids parsing an extensions.vector
-- signature on projects where migration 008 was never installed.
-- -----------------------------------------------------------------------------

do $cleanup$
declare
  legacy_function record;
begin
  for legacy_function in
    select
      namespace.nspname as schema_name,
      proc.proname as function_name,
      pg_get_function_identity_arguments(proc.oid) as identity_arguments
    from pg_proc as proc
    join pg_namespace as namespace
      on namespace.oid = proc.pronamespace
    where namespace.nspname = 'public'
      and proc.proname in (
        'search_knowledge_base',
        'sync_kb_collection_document_count',
        'sync_kb_document_chunk_count'
      )
  loop
    execute format(
      'drop function if exists %I.%I(%s) cascade',
      legacy_function.schema_name,
      legacy_function.function_name,
      legacy_function.identity_arguments
    );
  end loop;
end;
$cleanup$;

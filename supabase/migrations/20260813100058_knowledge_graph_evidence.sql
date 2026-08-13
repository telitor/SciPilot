-- Trace generated private graph nodes and edges back to the owning paper.
-- Writes are performed by the trusted backend; authenticated users receive
-- read-only access to their own evidence rows.

create unique index if not exists idx_knowledge_nodes_id_owner_unique
  on public.knowledge_nodes(id, user_id);

create unique index if not exists idx_knowledge_edges_id_owner_unique
  on public.knowledge_edges(id, user_id);

create table if not exists public.knowledge_graph_evidence (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid,
  paper_id uuid not null,
  node_id uuid,
  edge_id uuid,
  section_heading text,
  citation text,
  excerpt text,
  created_at timestamp with time zone not null default now(),
  constraint knowledge_graph_evidence_one_target_check
    check (num_nonnulls(node_id, edge_id) = 1),
  constraint knowledge_graph_evidence_paper_owner_fk
    foreign key (paper_id, user_id)
    references public.papers(id, user_id)
    on delete cascade,
  constraint knowledge_graph_evidence_project_owner_fk
    foreign key (project_id, user_id)
    references public.research_projects(id, user_id)
    on delete set null (project_id),
  constraint knowledge_graph_evidence_node_owner_fk
    foreign key (node_id, user_id)
    references public.knowledge_nodes(id, user_id)
    on delete cascade,
  constraint knowledge_graph_evidence_edge_owner_fk
    foreign key (edge_id, user_id)
    references public.knowledge_edges(id, user_id)
    on delete cascade
);

create unique index if not exists idx_knowledge_graph_evidence_paper_node
  on public.knowledge_graph_evidence(paper_id, node_id)
  where node_id is not null;

create unique index if not exists idx_knowledge_graph_evidence_paper_edge
  on public.knowledge_graph_evidence(paper_id, edge_id)
  where edge_id is not null;

create index if not exists idx_knowledge_graph_evidence_user_paper
  on public.knowledge_graph_evidence(user_id, paper_id, created_at desc);

create index if not exists idx_knowledge_graph_evidence_project_owner
  on public.knowledge_graph_evidence(project_id, user_id)
  where project_id is not null;

create index if not exists idx_knowledge_graph_evidence_node
  on public.knowledge_graph_evidence(node_id)
  where node_id is not null;

create index if not exists idx_knowledge_graph_evidence_edge
  on public.knowledge_graph_evidence(edge_id)
  where edge_id is not null;

alter table public.knowledge_graph_evidence enable row level security;

drop policy if exists knowledge_graph_evidence_select_own
  on public.knowledge_graph_evidence;
create policy knowledge_graph_evidence_select_own
on public.knowledge_graph_evidence
for select
to authenticated
using ((select auth.uid()) is not null and (select auth.uid()) = user_id);

revoke all on table public.knowledge_graph_evidence from anon, authenticated;
grant select on table public.knowledge_graph_evidence to authenticated;
grant all on table public.knowledge_graph_evidence to service_role;

create or replace function public.cleanup_paper_knowledge_graph()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  delete from public.knowledge_edges
  where user_id = old.user_id
    and id in (
      select evidence.edge_id
      from public.knowledge_graph_evidence as evidence
      where evidence.paper_id = old.id
        and evidence.user_id = old.user_id
        and evidence.edge_id is not null
    )
    and not exists (
      select 1
      from public.knowledge_graph_evidence as other_evidence
      where other_evidence.edge_id = knowledge_edges.id
        and other_evidence.user_id = old.user_id
        and other_evidence.paper_id <> old.id
    );

  delete from public.knowledge_nodes
  where user_id = old.user_id
    and id in (
      select evidence.node_id
      from public.knowledge_graph_evidence as evidence
      where evidence.paper_id = old.id
        and evidence.user_id = old.user_id
        and evidence.node_id is not null
    )
    and not exists (
      select 1
      from public.knowledge_graph_evidence as other_evidence
      where other_evidence.node_id = knowledge_nodes.id
        and other_evidence.user_id = old.user_id
        and other_evidence.paper_id <> old.id
    )
    and not exists (
      select 1
      from public.knowledge_edges as remaining_edge
      where remaining_edge.source_node_id = knowledge_nodes.id
         or remaining_edge.target_node_id = knowledge_nodes.id
    );
  return old;
end;
$$;

revoke all on function public.cleanup_paper_knowledge_graph()
  from public, anon, authenticated;
grant execute on function public.cleanup_paper_knowledge_graph()
  to service_role;

drop trigger if exists cleanup_paper_knowledge_graph_before_delete
  on public.papers;
create trigger cleanup_paper_knowledge_graph_before_delete
before delete on public.papers
for each row execute function public.cleanup_paper_knowledge_graph();

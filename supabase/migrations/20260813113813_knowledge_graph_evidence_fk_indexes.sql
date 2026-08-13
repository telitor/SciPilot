-- Cover the composite ownership foreign keys introduced by graph evidence.
create index if not exists idx_knowledge_graph_evidence_edge_owner_fk
  on public.knowledge_graph_evidence(edge_id, user_id)
  where edge_id is not null;

create index if not exists idx_knowledge_graph_evidence_node_owner_fk
  on public.knowledge_graph_evidence(node_id, user_id)
  where node_id is not null;

create index if not exists idx_knowledge_graph_evidence_paper_owner_fk
  on public.knowledge_graph_evidence(paper_id, user_id);

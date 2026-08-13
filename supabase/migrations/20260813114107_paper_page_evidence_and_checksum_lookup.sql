-- Preserve page-level provenance without invalidating existing evidence rows.
alter table public.knowledge_graph_evidence
  add column if not exists page_start integer,
  add column if not exists page_end integer;

alter table public.knowledge_graph_evidence
  add constraint knowledge_graph_evidence_page_start_check
    check (page_start is null or page_start > 0),
  add constraint knowledge_graph_evidence_page_end_check
    check (page_end is null or page_end > 0),
  add constraint knowledge_graph_evidence_page_range_check
    check (
      (page_start is null and page_end is null)
      or (
        page_start is not null
        and (page_end is null or page_end >= page_start)
      )
    );

-- Speed up same-user, same-project duplicate upload detection.
create index if not exists idx_papers_owner_project_checksum
  on public.papers(user_id, project_id, checksum_sha256)
  where project_id is not null and checksum_sha256 is not null;

create index if not exists idx_papers_owner_unassigned_checksum
  on public.papers(user_id, checksum_sha256)
  where project_id is null and checksum_sha256 is not null;

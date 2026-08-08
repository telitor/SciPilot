-- Cover the composite project ownership foreign keys in their declared order.
-- These indexes do not change or backfill any data.

create index if not exists idx_papers_project_owner
  on public.papers(project_id, user_id);

create index if not exists idx_conversations_project_owner
  on public.conversations(project_id, user_id);

create index if not exists idx_research_artifacts_project_owner
  on public.research_artifacts(project_id, user_id);

create index if not exists idx_activities_project_owner
  on public.activities(project_id, user_id);

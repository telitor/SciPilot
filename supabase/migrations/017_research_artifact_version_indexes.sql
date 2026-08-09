-- =============================================================================
-- Cover the foreign keys introduced by research artifact versioning.
-- These indexes keep ownership checks and user deletion work proportional to
-- the affected version chain instead of scanning all research artifacts.
-- =============================================================================

create index if not exists idx_research_artifacts_version_group_owner
  on public.research_artifacts(version_group_id, user_id);

create index if not exists idx_research_artifacts_parent_version_owner
  on public.research_artifacts(parent_version_id, user_id)
  where parent_version_id is not null;

create index if not exists idx_research_artifacts_confirmed_by
  on public.research_artifacts(confirmed_by)
  where confirmed_by is not null;

-- =============================================================================
-- Versioned review workflow for research artifacts.
-- Existing artifacts are preserved as version 1 drafts. Runtime generation
-- status remains separate from human review status.
-- =============================================================================

alter table public.research_artifacts
  add column if not exists review_status text not null default 'draft',
  add column if not exists version_group_id uuid,
  add column if not exists version integer not null default 1,
  add column if not exists parent_version_id uuid,
  add column if not exists confirmed_at timestamp with time zone,
  add column if not exists confirmed_by uuid references auth.users(id) on delete set null;

update public.research_artifacts
set version_group_id = id
where version_group_id is null;

alter table public.research_artifacts
  alter column version_group_id set not null;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'research_artifacts_id_user_unique'
      and conrelid = 'public.research_artifacts'::regclass
  ) then
    alter table public.research_artifacts
      add constraint research_artifacts_id_user_unique unique (id, user_id);
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conname = 'research_artifacts_review_status_check'
      and conrelid = 'public.research_artifacts'::regclass
  ) then
    alter table public.research_artifacts
      add constraint research_artifacts_review_status_check
      check (review_status in ('draft', 'confirmed', 'deprecated'));
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conname = 'research_artifacts_version_check'
      and conrelid = 'public.research_artifacts'::regclass
  ) then
    alter table public.research_artifacts
      add constraint research_artifacts_version_check
      check (version >= 1);
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conname = 'research_artifacts_confirmation_check'
      and conrelid = 'public.research_artifacts'::regclass
  ) then
    alter table public.research_artifacts
      add constraint research_artifacts_confirmation_check
      check (
        (confirmed_by is null or confirmed_by = user_id)
        and (review_status <> 'confirmed' or confirmed_at is not null)
      );
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conname = 'research_artifacts_version_group_owner_fk'
      and conrelid = 'public.research_artifacts'::regclass
  ) then
    alter table public.research_artifacts
      add constraint research_artifacts_version_group_owner_fk
      foreign key (version_group_id, user_id)
      references public.research_artifacts(id, user_id)
      on delete cascade;
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conname = 'research_artifacts_parent_version_owner_fk'
      and conrelid = 'public.research_artifacts'::regclass
  ) then
    alter table public.research_artifacts
      add constraint research_artifacts_parent_version_owner_fk
      foreign key (parent_version_id, user_id)
      references public.research_artifacts(id, user_id)
      on delete set null (parent_version_id);
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conname = 'research_artifacts_group_version_unique'
      and conrelid = 'public.research_artifacts'::regclass
  ) then
    alter table public.research_artifacts
      add constraint research_artifacts_group_version_unique
      unique (version_group_id, version);
  end if;
end
$$;

create index if not exists idx_research_artifacts_user_group_version
  on public.research_artifacts(user_id, version_group_id, version desc);

create index if not exists idx_research_artifacts_project_review_updated
  on public.research_artifacts(
    user_id,
    project_id,
    artifact_type,
    review_status,
    updated_at desc
  );

create index if not exists idx_research_artifacts_latest_confirmed
  on public.research_artifacts(user_id, version_group_id, version desc)
  where review_status = 'confirmed' and status = 'completed';

-- Historical versions are immutable from the public Data API. The backend
-- service role remains responsible for creating revisions and review changes.
revoke delete on table public.research_artifacts from authenticated;

-- =============================================================================
-- Project-scoped, human-approved research workflow.
-- Execution remains in research_jobs; this layer records the fixed task DAG,
-- user approvals, upstream dependencies and resulting research artifacts.
-- =============================================================================

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'research_jobs_id_user_unique'
  ) then
    alter table public.research_jobs
      add constraint research_jobs_id_user_unique unique (id, user_id);
  end if;
end $$;

create table if not exists public.agent_workflows (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid not null,
  name text not null default '科研任务流',
  status text not null default 'active',
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint agent_workflows_project_owner_fk
    foreign key (project_id, user_id)
    references public.research_projects(id, user_id)
    on delete restrict,
  constraint agent_workflows_project_unique unique (project_id, user_id),
  constraint agent_workflows_id_owner_project_unique unique (id, user_id, project_id),
  constraint agent_workflows_name_not_blank
    check (length(btrim(name)) between 1 and 120),
  constraint agent_workflows_status_check
    check (status in ('active', 'completed', 'archived'))
);

create table if not exists public.agent_tasks (
  id uuid primary key default gen_random_uuid(),
  workflow_id uuid not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid not null,
  task_key text not null,
  title text not null,
  agent_category text not null,
  position integer not null,
  status text not null default 'blocked',
  research_job_id uuid,
  output_paper_id uuid,
  output_artifact_id uuid,
  error_message text,
  started_at timestamp with time zone,
  approved_at timestamp with time zone,
  completed_at timestamp with time zone,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint agent_tasks_workflow_owner_fk
    foreign key (workflow_id, user_id, project_id)
    references public.agent_workflows(id, user_id, project_id)
    on delete restrict,
  constraint agent_tasks_research_job_owner_fk
    foreign key (research_job_id, user_id)
    references public.research_jobs(id, user_id)
    on delete set null (research_job_id),
  constraint agent_tasks_output_paper_owner_fk
    foreign key (output_paper_id, user_id)
    references public.papers(id, user_id)
    on delete set null (output_paper_id),
  constraint agent_tasks_output_artifact_owner_fk
    foreign key (output_artifact_id, user_id)
    references public.research_artifacts(id, user_id)
    on delete set null (output_artifact_id),
  constraint agent_tasks_id_owner_project_unique unique (id, user_id, project_id),
  constraint agent_tasks_workflow_key_unique unique (workflow_id, task_key),
  constraint agent_tasks_workflow_position_unique unique (workflow_id, position),
  constraint agent_tasks_key_check
    check (task_key in (
      'paper-reading',
      'problem-decomposition',
      'project-planning',
      'code-reproduction',
      'result-interpretation'
    )),
  constraint agent_tasks_status_check
    check (status in (
      'blocked', 'ready', 'in_progress', 'awaiting_approval',
      'completed', 'failed'
    )),
  constraint agent_tasks_position_check check (position between 1 and 5),
  constraint agent_tasks_title_not_blank check (length(btrim(title)) between 1 and 120),
  constraint agent_tasks_category_not_blank
    check (length(btrim(agent_category)) between 1 and 100)
);

create table if not exists public.agent_task_dependencies (
  task_id uuid not null,
  depends_on_task_id uuid not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid not null,
  created_at timestamp with time zone not null default now(),
  primary key (task_id, depends_on_task_id),
  constraint agent_task_dependencies_task_owner_fk
    foreign key (task_id, user_id, project_id)
    references public.agent_tasks(id, user_id, project_id)
    on delete cascade,
  constraint agent_task_dependencies_parent_owner_fk
    foreign key (depends_on_task_id, user_id, project_id)
    references public.agent_tasks(id, user_id, project_id)
    on delete cascade,
  constraint agent_task_dependencies_not_self check (task_id <> depends_on_task_id)
);

create index if not exists idx_agent_workflows_user_updated
  on public.agent_workflows(user_id, updated_at desc);

create index if not exists idx_agent_tasks_workflow_position
  on public.agent_tasks(user_id, workflow_id, position);

create index if not exists idx_agent_tasks_project_status
  on public.agent_tasks(user_id, project_id, status, updated_at desc);

create index if not exists idx_agent_tasks_research_job
  on public.agent_tasks(research_job_id, user_id)
  where research_job_id is not null;

create index if not exists idx_agent_tasks_output_artifact
  on public.agent_tasks(output_artifact_id, user_id)
  where output_artifact_id is not null;

create index if not exists idx_agent_tasks_output_paper
  on public.agent_tasks(output_paper_id, user_id)
  where output_paper_id is not null;

create index if not exists idx_agent_task_dependencies_parent
  on public.agent_task_dependencies(depends_on_task_id, user_id, project_id);

drop trigger if exists set_agent_workflows_updated_at on public.agent_workflows;
create trigger set_agent_workflows_updated_at
before update on public.agent_workflows
for each row execute function public.set_updated_at();

drop trigger if exists set_agent_tasks_updated_at on public.agent_tasks;
create trigger set_agent_tasks_updated_at
before update on public.agent_tasks
for each row execute function public.set_updated_at();

alter table public.agent_workflows enable row level security;
alter table public.agent_tasks enable row level security;
alter table public.agent_task_dependencies enable row level security;

create policy agent_workflows_select_own on public.agent_workflows
for select to authenticated using ((select auth.uid()) = user_id);

create policy agent_tasks_select_own on public.agent_tasks
for select to authenticated using ((select auth.uid()) = user_id);

create policy agent_task_dependencies_select_own on public.agent_task_dependencies
for select to authenticated using ((select auth.uid()) = user_id);

revoke all on table public.agent_workflows from anon, authenticated;
revoke all on table public.agent_tasks from anon, authenticated;
revoke all on table public.agent_task_dependencies from anon, authenticated;

grant select on table public.agent_workflows to authenticated;
grant select on table public.agent_tasks to authenticated;
grant select on table public.agent_task_dependencies to authenticated;

grant select, insert, update on table public.agent_workflows to service_role;
grant select, insert, update on table public.agent_tasks to service_role;
grant select, insert on table public.agent_task_dependencies to service_role;

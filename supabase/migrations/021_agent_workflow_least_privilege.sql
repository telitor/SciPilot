-- Keep workflow mutation behind FastAPI ownership checks. Physical deletion is
-- intentionally unavailable to the application service role in this version.

revoke delete on table public.agent_workflows from service_role;
revoke delete on table public.agent_tasks from service_role;
revoke update, delete on table public.agent_task_dependencies from service_role;

create index if not exists idx_agent_workflows_project_owner
  on public.agent_workflows(project_id, user_id);

create index if not exists idx_agent_tasks_project_owner
  on public.agent_tasks(project_id, user_id);

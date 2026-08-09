-- Close the remaining destructive privilege and cover workflow ownership FKs.

revoke truncate on table public.agent_workflows from service_role;
revoke truncate on table public.agent_tasks from service_role;
revoke truncate on table public.agent_task_dependencies from service_role;

create index if not exists idx_agent_tasks_workflow_owner
  on public.agent_tasks(workflow_id, user_id, project_id);

create index if not exists idx_agent_task_dependencies_task_owner
  on public.agent_task_dependencies(task_id, user_id, project_id);

create index if not exists idx_agent_task_dependencies_user
  on public.agent_task_dependencies(user_id);

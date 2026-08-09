-- Supabase may grant service_role default table privileges before explicit
-- grants run. Reset them so project memories cannot be physically deleted.

revoke all on table public.project_memories from service_role;
grant select, insert, update on table public.project_memories to service_role;

create index if not exists idx_project_memories_project_owner
  on public.project_memories(project_id, user_id);

-- Audited administrator role governance. Auth emails remain in auth.users only.

-- The browser only talks to FastAPI. Keep direct Data API profile access read-only;
-- RLS still limits that SELECT to the caller's own profile row.
revoke all on table public.profiles from anon, authenticated;
grant select on table public.profiles to authenticated;

create or replace function public.prevent_last_admin_demotion()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if old.role = 'admin' and new.role <> 'admin' then
    perform pg_catalog.pg_advisory_xact_lock(
      pg_catalog.hashtext('scipilot-admin-role-change')
    );
    if not exists (
      select 1
      from public.profiles
      where role = 'admin' and id <> old.id
    ) then
      raise exception 'Cannot demote the last administrator';
    end if;
  end if;
  return new;
end;
$$;

revoke all on function public.prevent_last_admin_demotion()
  from public, anon, authenticated;
grant execute on function public.prevent_last_admin_demotion() to service_role;

drop trigger if exists protect_last_admin_role on public.profiles;
create trigger protect_last_admin_role
before update of role on public.profiles
for each row execute function public.prevent_last_admin_demotion();

create table if not exists public.admin_role_audits (
  id uuid primary key default gen_random_uuid(),
  target_user_id uuid references auth.users(id) on delete set null,
  actor_user_id uuid references auth.users(id) on delete set null,
  previous_role text not null,
  new_role text not null,
  source text not null,
  reason text not null,
  created_at timestamp with time zone not null default now(),
  constraint admin_role_audits_previous_role_check
    check (previous_role in ('user', 'admin')),
  constraint admin_role_audits_new_role_check
    check (new_role in ('user', 'admin')),
  constraint admin_role_audits_role_change_check
    check (previous_role <> new_role),
  constraint admin_role_audits_source_check
    check (source in ('bootstrap-script', 'admin-api')),
  constraint admin_role_audits_reason_length_check
    check (length(btrim(reason)) between 3 and 500)
);

create index if not exists idx_admin_role_audits_created
  on public.admin_role_audits(created_at desc);

create index if not exists idx_admin_role_audits_target_created
  on public.admin_role_audits(target_user_id, created_at desc)
  where target_user_id is not null;

create index if not exists idx_admin_role_audits_actor_created
  on public.admin_role_audits(actor_user_id, created_at desc)
  where actor_user_id is not null;

alter table public.admin_role_audits enable row level security;

drop policy if exists admin_role_audits_no_direct_access
  on public.admin_role_audits;
create policy admin_role_audits_no_direct_access
on public.admin_role_audits
for all
to authenticated
using (false)
with check (false);

revoke all on table public.admin_role_audits
  from anon, authenticated, service_role;
grant select, insert on table public.admin_role_audits to service_role;

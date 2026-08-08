-- =============================================================================
-- Strengthen conversation ownership and message isolation.
-- =============================================================================

do $$
begin
  if exists (
    select 1
    from public.messages as message
    join public.conversations as conversation
      on conversation.id = message.conversation_id
    where message.user_id <> conversation.user_id
  ) then
    raise exception 'Cannot enforce conversation ownership: mismatched messages exist';
  end if;
end;
$$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'conversations_id_user_id_unique'
      and conrelid = 'public.conversations'::regclass
  ) then
    alter table public.conversations
      add constraint conversations_id_user_id_unique unique (id, user_id);
  end if;
end;
$$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'messages_conversation_owner_fk'
      and conrelid = 'public.messages'::regclass
  ) then
    alter table public.messages
      add constraint messages_conversation_owner_fk
      foreign key (conversation_id, user_id)
      references public.conversations(id, user_id)
      on delete cascade;
  end if;
end;
$$;

alter table public.conversations enable row level security;
alter table public.messages enable row level security;

drop policy if exists conversations_select_own on public.conversations;
create policy conversations_select_own
on public.conversations
for select
to authenticated
using ((select auth.uid()) = user_id);

drop policy if exists conversations_insert_own on public.conversations;
create policy conversations_insert_own
on public.conversations
for insert
to authenticated
with check ((select auth.uid()) = user_id);

drop policy if exists conversations_update_own on public.conversations;
create policy conversations_update_own
on public.conversations
for update
to authenticated
using ((select auth.uid()) = user_id)
with check ((select auth.uid()) = user_id);

drop policy if exists conversations_delete_own on public.conversations;
create policy conversations_delete_own
on public.conversations
for delete
to authenticated
using ((select auth.uid()) = user_id);

drop policy if exists messages_select_own on public.messages;
create policy messages_select_own
on public.messages
for select
to authenticated
using (
  (select auth.uid()) = user_id
  and exists (
    select 1
    from public.conversations as conversation
    where conversation.id = messages.conversation_id
      and conversation.user_id = (select auth.uid())
  )
);

drop policy if exists messages_insert_own on public.messages;
create policy messages_insert_own
on public.messages
for insert
to authenticated
with check (
  (select auth.uid()) = user_id
  and exists (
    select 1
    from public.conversations as conversation
    where conversation.id = messages.conversation_id
      and conversation.user_id = (select auth.uid())
  )
);

drop policy if exists messages_update_own on public.messages;
create policy messages_update_own
on public.messages
for update
to authenticated
using (
  (select auth.uid()) = user_id
  and exists (
    select 1
    from public.conversations as conversation
    where conversation.id = messages.conversation_id
      and conversation.user_id = (select auth.uid())
  )
)
with check (
  (select auth.uid()) = user_id
  and exists (
    select 1
    from public.conversations as conversation
    where conversation.id = messages.conversation_id
      and conversation.user_id = (select auth.uid())
  )
);

drop policy if exists messages_delete_own on public.messages;
create policy messages_delete_own
on public.messages
for delete
to authenticated
using (
  (select auth.uid()) = user_id
  and exists (
    select 1
    from public.conversations as conversation
    where conversation.id = messages.conversation_id
      and conversation.user_id = (select auth.uid())
  )
);

revoke all on table public.conversations, public.messages from anon;
grant select, insert, update, delete
on table public.conversations, public.messages
to authenticated, service_role;

-- Privacy-minimized AI run metadata and human-reviewed message feedback.
-- Prompt and response bodies intentionally remain in the existing messages table.

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'messages_id_owner_conversation_unique'
      and conrelid = 'public.messages'::regclass
  ) then
    alter table public.messages
      add constraint messages_id_owner_conversation_unique
      unique (id, user_id, conversation_id);
  end if;
end $$;

create table if not exists public.ai_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid,
  conversation_id uuid,
  message_id uuid,
  agent_id uuid references public.agents(id) on delete set null,
  module text not null,
  provider text not null,
  model text,
  status text not null,
  response_mode text,
  fallback_reason text,
  retrieval_count integer not null default 0,
  latency_ms integer not null,
  model_latency_ms integer,
  token_usage jsonb not null default '{}'::jsonb,
  created_at timestamp with time zone not null default now(),
  constraint ai_runs_project_owner_fk
    foreign key (project_id, user_id)
    references public.research_projects(id, user_id)
    on delete set null (project_id),
  constraint ai_runs_conversation_owner_fk
    foreign key (conversation_id, user_id)
    references public.conversations(id, user_id)
    on delete cascade,
  constraint ai_runs_message_owner_fk
    foreign key (message_id, user_id, conversation_id)
    references public.messages(id, user_id, conversation_id)
    on delete cascade,
  constraint ai_runs_id_owner_unique unique (id, user_id),
  constraint ai_runs_status_check
    check (status in ('succeeded', 'degraded', 'failed')),
  constraint ai_runs_module_not_blank
    check (length(btrim(module)) between 1 and 100),
  constraint ai_runs_provider_not_blank
    check (length(btrim(provider)) between 1 and 100),
  constraint ai_runs_counts_check
    check (
      retrieval_count >= 0
      and latency_ms >= 0
      and (model_latency_ms is null or model_latency_ms >= 0)
    ),
  constraint ai_runs_message_shape_check
    check (
      (message_id is null)
      or (conversation_id is not null)
    )
);

create table if not exists public.message_feedback (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  conversation_id uuid not null,
  message_id uuid not null,
  ai_run_id uuid,
  rating text not null,
  comment text,
  review_status text not null default 'pending',
  reviewed_at timestamp with time zone,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint message_feedback_message_owner_fk
    foreign key (message_id, user_id, conversation_id)
    references public.messages(id, user_id, conversation_id)
    on delete cascade,
  constraint message_feedback_run_owner_fk
    foreign key (ai_run_id, user_id)
    references public.ai_runs(id, user_id)
    on delete set null (ai_run_id),
  constraint message_feedback_rating_check
    check (rating in ('helpful', 'unhelpful')),
  constraint message_feedback_review_status_check
    check (review_status in ('pending', 'reviewed', 'rejected')),
  constraint message_feedback_comment_length_check
    check (comment is null or length(comment) <= 1000),
  constraint message_feedback_message_owner_unique
    unique (message_id, user_id)
);

create index if not exists idx_ai_runs_user_created
  on public.ai_runs(user_id, created_at desc);

create index if not exists idx_ai_runs_project_created
  on public.ai_runs(user_id, project_id, created_at desc)
  where project_id is not null;

create index if not exists idx_ai_runs_conversation_created
  on public.ai_runs(user_id, conversation_id, created_at desc)
  where conversation_id is not null;

create unique index if not exists idx_ai_runs_message_unique
  on public.ai_runs(message_id)
  where message_id is not null;

create index if not exists idx_ai_runs_agent_created
  on public.ai_runs(agent_id, created_at desc)
  where agent_id is not null;

create index if not exists idx_message_feedback_user_updated
  on public.message_feedback(user_id, updated_at desc);

create index if not exists idx_message_feedback_pending
  on public.message_feedback(review_status, created_at)
  where review_status = 'pending';

drop trigger if exists set_message_feedback_updated_at
  on public.message_feedback;
create trigger set_message_feedback_updated_at
before update on public.message_feedback
for each row execute function public.set_updated_at();

alter table public.ai_runs enable row level security;
alter table public.message_feedback enable row level security;

create policy ai_runs_select_own on public.ai_runs
for select to authenticated using ((select auth.uid()) = user_id);

create policy message_feedback_select_own on public.message_feedback
for select to authenticated using ((select auth.uid()) = user_id);

revoke all on table public.ai_runs from anon, authenticated, service_role;
revoke all on table public.message_feedback from anon, authenticated, service_role;

grant select, insert on table public.ai_runs to service_role;
grant select, insert, update on table public.message_feedback to service_role;

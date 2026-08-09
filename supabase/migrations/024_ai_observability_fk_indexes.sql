-- Cover composite foreign keys used by AI run observability and feedback.

create index if not exists idx_ai_runs_conversation_owner
  on public.ai_runs(conversation_id, user_id);

create index if not exists idx_ai_runs_message_owner
  on public.ai_runs(message_id, user_id, conversation_id);

create index if not exists idx_ai_runs_project_owner
  on public.ai_runs(project_id, user_id);

create index if not exists idx_message_feedback_message_owner
  on public.message_feedback(message_id, user_id, conversation_id);

create index if not exists idx_message_feedback_run_owner
  on public.message_feedback(ai_run_id, user_id);

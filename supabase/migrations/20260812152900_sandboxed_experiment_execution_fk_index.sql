-- Cover the composite ownership foreign key added by migration 029.

create index if not exists idx_experiment_runs_execution_job_owner
  on public.experiment_runs(execution_job_id, user_id)
  where execution_job_id is not null;

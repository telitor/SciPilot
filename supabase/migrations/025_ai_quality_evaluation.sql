-- Human-reviewed feedback and deterministic evaluation history.

alter table public.message_feedback
  add column if not exists reviewed_by uuid references auth.users(id) on delete set null,
  add column if not exists review_note text;

alter table public.message_feedback
  drop constraint if exists message_feedback_review_note_length_check;
alter table public.message_feedback
  add constraint message_feedback_review_note_length_check
  check (review_note is null or length(review_note) <= 1000);

create table if not exists public.evaluation_suites (
  id uuid primary key default gen_random_uuid(),
  slug text not null,
  name text not null,
  description text,
  module text not null,
  version integer not null default 1 check (version >= 1),
  is_active boolean not null default true,
  created_at timestamp with time zone not null default now(),
  constraint evaluation_suites_slug_version_unique unique (slug, version),
  constraint evaluation_suites_slug_not_blank check (length(btrim(slug)) between 1 and 100),
  constraint evaluation_suites_name_not_blank check (length(btrim(name)) between 1 and 200)
);

create table if not exists public.evaluation_cases (
  id uuid primary key default gen_random_uuid(),
  suite_id uuid not null references public.evaluation_suites(id) on delete cascade,
  case_key text not null,
  input jsonb not null,
  expected jsonb not null,
  created_at timestamp with time zone not null default now(),
  constraint evaluation_cases_suite_key_unique unique (suite_id, case_key),
  constraint evaluation_cases_key_not_blank check (length(btrim(case_key)) between 1 and 160)
);

create table if not exists public.evaluation_runs (
  id uuid primary key default gen_random_uuid(),
  suite_id uuid not null references public.evaluation_suites(id) on delete restrict,
  initiated_by uuid not null references auth.users(id) on delete restrict,
  mode text not null default 'offline',
  status text not null default 'running',
  provider text,
  model text,
  case_count integer not null default 0,
  passed_count integer not null default 0,
  failed_count integer not null default 0,
  metrics jsonb not null default '{}'::jsonb,
  config_snapshot jsonb not null default '{}'::jsonb,
  error_message text,
  started_at timestamp with time zone not null default now(),
  completed_at timestamp with time zone,
  constraint evaluation_runs_mode_check check (mode in ('offline', 'real-model')),
  constraint evaluation_runs_status_check check (status in ('running', 'completed', 'failed')),
  constraint evaluation_runs_counts_check check (
    case_count >= 0 and passed_count >= 0 and failed_count >= 0
    and passed_count + failed_count <= case_count
  ),
  constraint evaluation_runs_error_length_check check (error_message is null or length(error_message) <= 1000)
);

create table if not exists public.evaluation_results (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references public.evaluation_runs(id) on delete cascade,
  case_id uuid not null references public.evaluation_cases(id) on delete restrict,
  status text not null,
  rank integer,
  metrics jsonb not null default '{}'::jsonb,
  diagnostic text,
  created_at timestamp with time zone not null default now(),
  constraint evaluation_results_run_case_unique unique (run_id, case_id),
  constraint evaluation_results_status_check check (status in ('passed', 'failed')),
  constraint evaluation_results_rank_check check (rank is null or rank >= 1),
  constraint evaluation_results_diagnostic_length_check check (diagnostic is null or length(diagnostic) <= 1000)
);

create index if not exists idx_message_feedback_reviewed_by
  on public.message_feedback(reviewed_by) where reviewed_by is not null;
create index if not exists idx_evaluation_cases_suite
  on public.evaluation_cases(suite_id);
create index if not exists idx_evaluation_runs_suite_started
  on public.evaluation_runs(suite_id, started_at desc);
create index if not exists idx_evaluation_runs_initiator_started
  on public.evaluation_runs(initiated_by, started_at desc);
create index if not exists idx_evaluation_results_case
  on public.evaluation_results(case_id);

alter table public.evaluation_suites enable row level security;
alter table public.evaluation_cases enable row level security;
alter table public.evaluation_runs enable row level security;
alter table public.evaluation_results enable row level security;

revoke all on table public.evaluation_suites from anon, authenticated, service_role;
revoke all on table public.evaluation_cases from anon, authenticated, service_role;
revoke all on table public.evaluation_runs from anon, authenticated, service_role;
revoke all on table public.evaluation_results from anon, authenticated, service_role;

grant select on table public.evaluation_suites to service_role;
grant select on table public.evaluation_cases to service_role;
grant select, insert, update on table public.evaluation_runs to service_role;
grant select, insert on table public.evaluation_results to service_role;

insert into public.evaluation_suites (slug, name, description, module, version, is_active)
values (
  'rag-retrieval-baseline',
  'RAG 检索离线基线',
  '固定用例验证查询改写和融合重排，运行过程不调用外部模型。',
  'rag-retrieval',
  1,
  true
)
on conflict (slug, version) do update
set name = excluded.name,
    description = excluded.description,
    module = excluded.module,
    is_active = excluded.is_active;

with suite as (
  select id from public.evaluation_suites
  where slug = 'rag-retrieval-baseline' and version = 1
)
insert into public.evaluation_cases (suite_id, case_key, input, expected)
select suite.id, seed.case_key, seed.input::jsonb, seed.expected::jsonb
from suite
cross join (
  values
    (
      'defect-prediction-metrics',
      '{"query":"这些论文中，软件缺陷预测常用哪些评价指标？","original":[["overview:0","软件缺陷预测综述","本文概述了缺陷预测任务。",0.91],["metrics:0","缺陷预测评价","常用评价指标包括 F1、AUC、精确率和召回率。",0.82]],"rewritten":[["metrics:0","缺陷预测评价","常用评价指标包括 F1、AUC、精确率和召回率。",0.88],["dataset:0","缺陷数据集","实验采用 NASA 数据集。",0.73]]}',
      '{"relevant_ids":["metrics:0"]}'
    ),
    (
      'paper-core-algorithm',
      '{"query":"请问这篇论文主要运用了什么算法？","original":[["intro:0","研究背景","本文研究复杂网络中的分类问题。",0.92],["method:2","核心方法","模型使用图卷积网络和注意力机制。",0.80]],"rewritten":[["method:2","核心方法","模型使用图卷积网络和注意力机制。",0.90],["experiment:1","实验设置","训练使用 Adam 优化器。",0.76]]}',
      '{"relevant_ids":["method:2"]}'
    ),
    (
      'paper-limitations',
      '{"query":"这篇论文有哪些不足？","original":[["conclusion:0","结论","方法在三个数据集上取得提升。",0.89],["limitations:0","局限性","样本规模较小，跨项目泛化能力仍需验证。",0.78]],"rewritten":[["limitations:0","局限性","样本规模较小，跨项目泛化能力仍需验证。",0.87],["future:0","未来工作","后续将扩展到更多项目。",0.74]]}',
      '{"relevant_ids":["limitations:0"]}'
    )
) as seed(case_key, input, expected)
on conflict (suite_id, case_key) do update
set input = excluded.input, expected = excluded.expected;

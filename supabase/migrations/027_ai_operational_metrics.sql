-- Online AI usage, cost metadata, in-app alerts, and bounded real-model smoke cases.

alter table public.ai_runs
  add column if not exists input_tokens integer not null default 0,
  add column if not exists output_tokens integer not null default 0,
  add column if not exists usage_source text not null default 'unavailable',
  add column if not exists estimated_cost_cny numeric(14, 6);

alter table public.ai_runs
  drop constraint if exists ai_runs_token_counts_check;
alter table public.ai_runs
  add constraint ai_runs_token_counts_check
  check (input_tokens >= 0 and output_tokens >= 0);

alter table public.ai_runs
  drop constraint if exists ai_runs_usage_source_check;
alter table public.ai_runs
  add constraint ai_runs_usage_source_check
  check (usage_source in ('provider', 'estimated', 'unavailable'));

alter table public.ai_runs
  drop constraint if exists ai_runs_estimated_cost_check;
alter table public.ai_runs
  add constraint ai_runs_estimated_cost_check
  check (estimated_cost_cny is null or estimated_cost_cny >= 0);

create index if not exists idx_ai_runs_created_status
  on public.ai_runs(created_at desc, status);

create index if not exists idx_ai_runs_module_created
  on public.ai_runs(module, created_at desc);

create table if not exists public.ai_alerts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  module text not null,
  alert_type text not null,
  severity text not null default 'warning',
  status text not null default 'open',
  title text not null,
  detail text not null,
  metric_value numeric,
  threshold_value numeric,
  occurrence_count integer not null default 1,
  dedupe_key text not null unique,
  first_seen_at timestamp with time zone not null default now(),
  last_seen_at timestamp with time zone not null default now(),
  acknowledged_at timestamp with time zone,
  acknowledged_by uuid references auth.users(id) on delete set null,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint ai_alerts_module_not_blank check (length(btrim(module)) between 1 and 100),
  constraint ai_alerts_type_check check (
    alert_type in ('failure-rate', 'degraded-rate', 'p95-latency', 'daily-volume')
  ),
  constraint ai_alerts_severity_check check (severity in ('warning', 'critical')),
  constraint ai_alerts_status_check check (status in ('open', 'acknowledged', 'resolved')),
  constraint ai_alerts_occurrence_check check (occurrence_count >= 1),
  constraint ai_alerts_title_length_check check (length(btrim(title)) between 1 and 200),
  constraint ai_alerts_detail_length_check check (length(detail) between 1 and 1000)
);

create index if not exists idx_ai_alerts_status_last_seen
  on public.ai_alerts(status, last_seen_at desc);

create index if not exists idx_ai_alerts_user_last_seen
  on public.ai_alerts(user_id, last_seen_at desc)
  where user_id is not null;

create index if not exists idx_ai_alerts_acknowledged_by
  on public.ai_alerts(acknowledged_by)
  where acknowledged_by is not null;

drop trigger if exists set_ai_alerts_updated_at on public.ai_alerts;
create trigger set_ai_alerts_updated_at
before update on public.ai_alerts
for each row execute function public.set_updated_at();

alter table public.ai_alerts enable row level security;

drop policy if exists ai_alerts_no_direct_access on public.ai_alerts;
create policy ai_alerts_no_direct_access
on public.ai_alerts
for all
to authenticated
using (false)
with check (false);

revoke all on table public.ai_alerts from anon, authenticated, service_role;
grant select, insert, update on table public.ai_alerts to service_role;

insert into public.evaluation_suites (
  slug, name, description, module, version, is_active
)
values (
  'xunfei-real-model-smoke',
  '讯飞真实模型冒烟评测',
  '每个核心智能模块仅执行一个短用例，不调用知识库，单次输出上限 512 Token。',
  'real-model-smoke',
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
  where slug = 'xunfei-real-model-smoke' and version = 1
)
insert into public.evaluation_cases (suite_id, case_key, input, expected)
select suite.id, seed.case_key, seed.input::jsonb, seed.expected::jsonb
from suite
cross join (
  values
    (
      'paper-reading',
      '{"category":"paper-reading","system_prompt":"你是论文精读助手。","prompt":"根据以下摘要，用两句话概括研究问题与方法：本文研究软件缺陷预测，使用图神经网络建模代码依赖，并在公开数据集上与传统模型比较。","max_tokens":512}',
      '{"min_length":20,"required_any":["缺陷预测","图神经网络"],"forbidden":["临时测试回复"]}'
    ),
    (
      'problem-decomposition',
      '{"category":"problem-decomposition","system_prompt":"你是问题拆解助手。","prompt":"将“提高跨项目软件缺陷预测的泛化能力”拆成三个可执行研究子问题，回答保持简洁。","max_tokens":512}',
      '{"min_length":30,"required_any":["数据","模型","评估","泛化"],"forbidden":["临时测试回复"]}'
    ),
    (
      'project-planning',
      '{"category":"project-planning","system_prompt":"你是实验规划助手。","prompt":"为比较两个缺陷预测模型给出三步最小实验路线，包含数据划分与评价指标。","max_tokens":512}',
      '{"min_length":30,"required_any":["数据","指标","模型"],"forbidden":["临时测试回复"]}'
    ),
    (
      'code-reproduction',
      '{"category":"code-reproduction","system_prompt":"你是代码复现助手。","prompt":"为一个 Python 机器学习仓库给出三步安全复现清单，不声称已经执行代码。","max_tokens":512}',
      '{"min_length":30,"required_any":["环境","依赖","运行","验证"],"forbidden":["已经执行","临时测试回复"]}'
    ),
    (
      'result-interpretation',
      '{"category":"result-interpretation","system_prompt":"你是结果分析助手。","prompt":"模型 A 的 F1 为 0.82，模型 B 为 0.79；请给出谨慎解释并指出还缺少什么证据。","max_tokens":512}',
      '{"min_length":30,"required_any":["F1","显著","方差","置信","重复"],"forbidden":["临时测试回复"]}'
    ),
    (
      'dashboard-chat',
      '{"category":"dashboard-chat","system_prompt":"你是 SciPilot 科研对话助手。","prompt":"用一句话说明为什么实验需要固定随机种子。","max_tokens":512}',
      '{"min_length":15,"required_any":["复现","随机","一致"],"forbidden":["临时测试回复"]}'
    )
) as seed(case_key, input, expected)
on conflict (suite_id, case_key) do update
set input = excluded.input,
    expected = excluded.expected;

-- =========================================
-- SciCopilot v0.1
-- 004_add_multi_agents.sql
-- Add three public agents for the shared /chat loop.
-- =========================================

insert into public.agents (
  name,
  description,
  system_prompt,
  category,
  is_public
)
values (
  '问题拆解助手',
  '将复杂软件工程问题拆解为目标、约束、子任务与解决路径。',
  '你是问题拆解助手，擅长将复杂软件工程问题拆解为背景、目标、约束、输入输出、核心难点、子任务和可执行路径。回答应结构清晰、步骤明确、适合项目开发与科研分析。',
  'problem-decomposition',
  true
)
on conflict (name) do update
set
  description = excluded.description,
  system_prompt = excluded.system_prompt,
  category = excluded.category,
  is_public = excluded.is_public;

insert into public.agents (
  name,
  description,
  system_prompt,
  category,
  is_public
)
values (
  '结果分析助手',
  '分析实验结果、评价指标、对比现象与结论解释。',
  '你是结果分析助手，擅长解释实验结果、指标变化、对比结论、异常现象和实验可信度。回答应结合数据含义、可能原因、结论边界和改进建议。',
  'result-interpretation',
  true
)
on conflict (name) do update
set
  description = excluded.description,
  system_prompt = excluded.system_prompt,
  category = excluded.category,
  is_public = excluded.is_public;

insert into public.agents (
  name,
  description,
  system_prompt,
  category,
  is_public
)
values (
  '代码复现助手',
  '辅助论文代码复现、环境配置、模块拆解与报错定位。',
  '你是代码复现助手，擅长帮助用户理解论文代码、配置环境、拆解模块、规划复现步骤、定位运行错误。回答应具体、可执行、按步骤给出。',
  'code-reproduction',
  true
)
on conflict (name) do update
set
  description = excluded.description,
  system_prompt = excluded.system_prompt,
  category = excluded.category,
  is_public = excluded.is_public;

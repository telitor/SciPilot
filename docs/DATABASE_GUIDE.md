# SciPilot 数据库使用指南

## 1. 是否需要 Supabase

建议保留 Supabase。SciPilot 当前需要的 PostgreSQL 数据库、用户登录、私有 PDF 存储和行级权限（RLS），Supabase 可以在一个项目中同时提供。前端只访问 FastAPI，FastAPI 再访问 Supabase；不要让浏览器持有服务器 Secret Key。

数据流：

```text
React 前端 -> FastAPI -> Supabase Auth / Postgres / Storage
```

## 2. 首次部署

迁移文件位于 `supabase/migrations/`，必须按编号执行。

> 当前项目已经完成 006–008 部署并通过在线检查；本节用于新环境复现。

- 新 Supabase 项目：执行 `001` 到 `008`。
- 已经执行过原仓库 `001` 到 `005`：只执行 `006`、`007`、`008`。
- `006` 创建完整工作区数据层、RLS 和私有 `papers` Storage bucket。
- `007` 幂等写入公开资料目录与入门知识图谱；重复执行不会产生重复数据。
- `008` 创建真正的 RAG 知识库：文档入库、切块、全文/模糊/向量混合检索、摄取任务、引用追踪、RLS 和私有 `knowledge-base` Storage bucket。

最简单的方式是在 Supabase Dashboard 的 SQL Editor 中依次运行文件。使用 Supabase CLI 时，可在仓库根目录执行：

```bash
npx supabase login
npx supabase link --project-ref YOUR_PROJECT_REF
npx supabase db push
```

CLI 链接项目会要求 Supabase 登录或数据库凭据。Publishable/Anon Key 和 Secret/Service Role Key 都不能代替数据库迁移凭据。

后端 `backend/.env` 使用以下变量名：

```dotenv
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY
SUPABASE_SECRET_KEY=YOUR_SERVER_SECRET_KEY
```

代码同时兼容旧名称 `SUPABASE_ANON_KEY` 和 `SUPABASE_SERVICE_ROLE_KEY`。
`.env` 不得提交到 GitHub。

## 3. 数据库能做什么

| 表/资源 | 用途 | 可见范围 |
|---|---|---|
| `profiles` | 用户名、头像、简介、偏好 | 仅本人 |
| `agents` | SciPilot 智能体及系统提示词 | 公开智能体可读 |
| `conversations` / `messages` | 分模块保存对话、引用和模型元数据 | 仅本人 |
| `papers` | 用户论文元数据与处理状态 | 仅本人 |
| `paper_reports` | 论文精读报告、章节和摘要 | 仅论文所有者 |
| `research_artifacts` | 问题拆解、实验路线、代码复现、结果分析等 JSON 结果 | 仅本人 |
| `activities` | 首页/个人中心的最近活动 | 仅本人 |
| `catalog_resources` | 经核实的公开论文、数据集、仓库和基准目录 | 公开只读 |
| `knowledge_nodes` / `knowledge_edges` | 公共知识图谱和用户私有图谱 | 公共数据或本人数据 |
| `kb_collections` | 组织个人或管理员维护的公共知识库 | 公共集合或本人集合 |
| `kb_documents` / `kb_chunks` | 保存来源元数据、文本切块、全文索引和可选 1536 维向量 | 公共集合内容或本人内容 |
| `kb_ingestion_jobs` | 记录解析、OCR、切块和向量化进度及失败原因 | 仅本人 |
| `kb_retrievals` / `kb_citations` | 留存检索问题、回答和逐条引用来源，便于追溯 | 仅本人 |
| Storage `papers` bucket | 原始 PDF，最大 25 MiB | 仅路径首段对应的用户 |
| Storage `knowledge-base` bucket | 知识库 PDF、TXT、Markdown 原文件，最大 25 MiB | 仅路径首段对应的用户 |

注册成功后，数据库触发器会自动创建 `profiles`。删除 Auth 用户时，其私有数据库记录会级联删除；论文文件应由后端在删除论文时同时删除。

## 4. 应添加哪些数据

普通用户不需要直接操作数据库，只需要通过 SciPilot：

1. 注册账号并完善用户名、头像、简介和偏好。
2. 上传需要精读的合法 PDF，或填写论文 URL、arXiv ID、DOI。
3. 输入研究方向、实验目标、代码仓库 URL、错误日志和实验结果。
4. FastAPI 会把报告和各研究模块结果写入相应表，并记录最近活动。

管理员可以继续维护公共资料。建议每批公开资料新增一个后续编号迁移，例如 `009_add_catalog_resources.sql`，使用稳定 `slug` 和 `on conflict (slug) do update`，不要手工修改 `007` 的历史内容。只保存公开元数据和官方链接；论文全文、数据集和源代码仍受原许可证约束。

当前公共知识通过 `backend/scripts/seed_software_engineering_kb.py` 幂等维护：
12 篇原创中文软件工程知识卡，所有条目都有官方链接、许可边界、主题和适用智能体类别。
普通用户可以检索，但不能修改 `system_managed` 集合。

私有 PDF 的对象路径固定为：

```text
<auth-user-uuid>/<paper-uuid>/<original-file-name>
```

## 5. 知识库部署与验收

### 5.1 它与原有“资料目录/知识图谱”的区别

`catalog_resources`、`knowledge_nodes` 和 `knowledge_edges` 适合保存公开资料的元数据和明确的实体关系，但不能承担文档问答。`008_knowledge_base.sql` 新增的是 RAG 数据层：

```text
上传 PDF/TXT/Markdown
  -> 私有 Storage 原文件
  -> kb_documents 来源记录
  -> 文本提取与 kb_chunks 切块
  -> PostgreSQL 全文/中文模糊检索
  -> 可选 pgvector 1536 维语义检索
  -> 带 chunk/document 引用的回答
```

不配置向量模型时，`query_embedding` 传 `null`，全文检索和 `pg_trgm` 中文模糊检索仍可独立工作。配置兼容 OpenAI Embeddings 的服务后，后端会写入 1536 维向量并自动使用混合排序。`search_knowledge_base` RPC 只授权给后端 `service_role`，浏览器不能直接调用并伪造其他用户 UUID；前端必须通过已登录的 FastAPI 接口检索。

### 5.2 执行迁移

在已经完成 `001`–`007` 的 Supabase 项目中，于 SQL Editor 完整执行：

```text
supabase/migrations/008_knowledge_base.sql
```

这会启用 `vector` 与 `pg_trgm` 扩展，创建 6 张知识库表、检索 RPC、索引、RLS 策略和私有文件桶。迁移本身不写入论文正文或其他受版权保护全文；执行种子脚本后，当前项目写入 12 条题录、官方链接和 SciPilot 原创摘要，不复制第三方全文。

知识库文件路径固定为：

```text
<auth-user-uuid>/<collection-uuid>/<generated-name>-<original-file-name>
```

即使集合设为公开，原始文件仍保持私有；公开用户只能读取允许公开的文本切块和来源元数据。

### 5.3 检查结构

在 SQL Editor 中运行：

```sql
select extname
from pg_extension
where extname in ('vector', 'pg_trgm')
order by extname;

select to_regclass('public.kb_collections') as collections,
       to_regclass('public.kb_documents') as documents,
       to_regclass('public.kb_chunks') as chunks,
       to_regprocedure(
         'public.search_knowledge_base(text,extensions.vector,integer,uuid,uuid)'
       ) as search_rpc;

select id, name, public, file_size_limit
from storage.buckets
where id = 'knowledge-base';
```

预期两个扩展、三张核心表和 `search_knowledge_base` RPC 均非空，`knowledge-base` bucket 的 `public` 为 `false`。

在已登录 API 中完成一次验证：

1. 创建一个知识库集合。
2. 上传 UTF-8 的 TXT/Markdown 或包含可提取文本的 PDF；扫描版 PDF 需先 OCR。
3. 确认文档 `status = 'ready'`、`chunk_count > 0`。
4. 用标题原词、中文近似词各检索一次。
5. 开启 Embeddings 后再检索一次，确认返回项包含 `chunk_id`、`document_id`、`content`、`score` 和来源字段。
6. 用第二个账号确认无法读取第一个账号的私有集合、文档、切块和原始文件，但可以读取系统公共知识。
7. 分别调用 5 个智能体，确认回答包含 `[n]` 引用，并在 `kb_retrievals` / `kb_citations` 留下审计记录。

## 6. 其他数据库部署后检查

在 SQL Editor 中运行：

```sql
select slug, resource_type, title
from public.catalog_resources
order by slug;

select count(*) as public_nodes
from public.knowledge_nodes
where is_public = true;

select count(*) as public_edges
from public.knowledge_edges
where is_public = true;

select id, name, public, file_size_limit
from storage.buckets
where id = 'papers';
```

预期目录有 7 条公开资源，知识图谱有 15 个公共节点、14 条公共边，`papers` bucket 的 `public` 为 `false`。

再注册两个测试账号，确认账号 A 无法读取账号 B 的 `profiles`、对话、论文、报告、研究产物和 Storage 文件。后端使用服务器 Secret Key，会绕过 RLS，因此每个 API 仍必须按当前用户过滤 `user_id`。

## 7. 密钥安全

- Publishable Key 可以用于受 RLS 保护的客户端请求，但 SciPilot 当前不需要把它放进前端。
- Secret/Service Role Key 只能放在后端环境变量或部署平台的 Secret 管理中。
- 不得把 `.env`、日志中的密钥或任何真实 Key 提交到 GitHub。
- Secret Key 一旦出现在聊天、Issue、截图或提交记录中，应立即在 Supabase 中轮换，并更新后端部署环境。

## 8. 需要提交到 GitHub

数据库部分需要提交：

```text
supabase/
  migrations/
    001_init_schema.sql
    002_updated_at_trigger.sql
    003_rls_policies.sql
    004_add_multi_agents.sql
    005_add_project_planning_agent.sql
    006_workspace_data_layer.sql
    007_seed_public_research_catalog.sql
    008_knowledge_base.sql
docs/
  DATABASE_GUIDE.md
backend/
  scripts/seed_software_engineering_kb.py
  scripts/e2e_knowledge_base.py
  scripts/e2e_agent_knowledge.py
```

`supabase/migrations/` 和 `docs/` 是仓库根目录下应新增的文件夹。不要提交 `backend/.env`；只提交不含真实密钥的 `backend/.env.example`。

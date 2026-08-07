# SciPilot 数据库部署与使用指南

## 1. Supabase 现在负责什么

SciPilot 保留 Supabase，但职责收敛为用户认证和业务数据：

```text
React -> FastAPI -> Supabase Auth / PostgreSQL / papers Storage
                 -> 讯飞 ChatDoc（论文知识库）
                 -> 讯飞 MaaS（模型推理）
```

Supabase 不再承担 RAG 论文库的文档存储、切块、向量检索和引用审计。论文知识库由星火 ChatDoc 托管；知识检索结果只在请求期间作为 MaaS 上下文使用。

浏览器仅访问 FastAPI，不直接持有 Supabase Secret/Service Role Key。

## 2. 数据库保留内容

| 表/资源 | 用途 | 访问边界 |
| --- | --- | --- |
| Supabase Auth | 注册、登录、刷新与注销会话 | Supabase 认证系统 |
| `profiles` | 用户名、头像、简介和偏好 | 仅本人 |
| `agents` | SciPilot 智能体及系统提示词 | 公开智能体可读 |
| `conversations` / `messages` | 分模块对话、回答引用和模型元数据 | 仅本人 |
| `papers` | 用户论文元数据和处理状态 | 仅本人 |
| `paper_reports` | 论文精读报告、章节和摘要 | 仅论文所有者 |
| `research_artifacts` | 问题拆解、实验路线、代码复现和结果分析 JSON | 仅本人 |
| `activities` | 仪表盘与个人中心活动记录 | 仅本人 |
| `catalog_resources` | 经核实的公开论文、数据集、仓库和基准目录 | 登录用户公开只读 |
| `knowledge_nodes` / `knowledge_edges` | 公共和个人知识图谱关系 | 公共数据或本人数据 |
| Storage `papers` bucket | 用户上传的论文原文件 | 私有，按用户路径隔离 |

`knowledge_nodes` / `knowledge_edges` 是结构化知识图谱，不是旧 RAG 知识库，迁移时必须保留。

## 3. 已移除的旧知识库结构

旧版 Supabase RAG 曾使用下列结构，当前版本不再由应用创建、读取或写入：

```text
kb_collections
kb_documents
kb_chunks
kb_ingestion_jobs
kb_retrievals
kb_citations
search_knowledge_base(...)
Storage knowledge-base bucket
```

对应的文档、切块和向量已由星火 ChatDoc 的 Repo 管理。不要在新功能中重新引入这些表，也不要把 ChatDoc 的 APISecret 或文件全文写入业务表。

## 4. 首次部署

迁移文件位于 `supabase/migrations/`。在 Supabase SQL Editor 中按文件名编号执行目录中的全部迁移，或使用 Supabase CLI：

```powershell
npx supabase login
npx supabase link --project-ref YOUR_PROJECT_REF
npx supabase db push
```

迁移说明：

- `001`–`005`：基础用户、Agent、论文与会话结构。
- `006`：工作区业务数据、RLS 与私有 `papers` Storage bucket。
- `007`：公开资料目录与知识图谱种子。
- `008_knowledge_base.sql`：已从当前仓库移除的旧 Supabase RAG 迁移；不要在新项目执行。
- `009_remove_legacy_knowledge_base.sql`：为升级项目幂等移除旧知识库表、函数、策略和桶配置，同时保留其他业务结构；新项目执行它也是安全的。

新项目按当前目录依次执行 `001`–`007` 和 `009`。编号缺少 `008` 是有意的：该文件属于已淘汰实现，保留 `009` 是为了让曾执行过旧迁移的部署也能升级到相同最终 schema。

> 如果旧 `knowledge-base` Storage bucket 内仍有对象，Supabase 可能拒绝直接删除 bucket。应先在控制台核对并删除旧对象，再重新执行/补充删除 bucket 的清理步骤。不要删除 `papers` bucket。

## 5. 升级现有项目

曾经运行旧 `008_knowledge_base.sql` 的项目只需执行最新清理迁移：

```text
supabase/migrations/009_remove_legacy_knowledge_base.sql
```

执行前建议：

1. 确认生产代码已经切换到 `xunfei_knowledge_base_service.py`。
2. 如旧知识库仍有必须保留的数据，先导出元数据或原文件。
3. 在 Supabase 控制台确认目标只包含 `kb_*` 旧表、旧检索函数和 `knowledge-base` bucket。
4. 创建数据库备份或恢复点。
5. 执行迁移并完成第 8 节核验。

清理会删除旧知识库数据，属于不可逆操作；它不应删除 Auth 用户、业务论文、会话、研究产物、活动、资料目录或知识图谱。

## 6. 后端连接配置

复制 `backend/.env.example` 为 `backend/.env`，填写：

```dotenv
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY
SUPABASE_SECRET_KEY=YOUR_SERVER_SECRET_KEY
```

代码可以兼容旧名称 `SUPABASE_ANON_KEY` 和 `SUPABASE_SERVICE_ROLE_KEY`，新部署建议使用示例文件中的新名称。

- Publishable Key 可用于受 RLS 保护的客户端流程，但 SciPilot 当前仍由 FastAPI 代理。
- Secret/Service Role Key 会绕过 RLS，只能存在于后端环境或部署平台 Secret 管理。
- `backend/.env` 不得提交。

## 7. Auth、RLS 与对象路径

注册成功后，数据库触发器会创建对应 `profiles` 记录。用户私有表启用 RLS，普通会话只能读取自己的数据。

论文文件路径使用用户 ID 作为首段：

```text
<auth-user-uuid>/<paper-uuid>/<original-file-name>
```

`papers` bucket 必须保持私有。后端使用服务器 Secret Key 时可绕过 RLS，因此每个 API 仍必须从已验证 JWT 获取用户 ID，并在查询中显式过滤所有权；不能信任请求体传入的 `user_id`。

建议用两个测试账号做越权验证：

1. 账号 A、B 分别创建论文、会话和研究产物。
2. 用 A 的令牌尝试请求 B 的资源 ID，预期为 `404` 或 `403`。
3. 确认 A 无法读取 B 的 Storage 对象。
4. 确认两个账号都可读取公开 Agent、资料目录和公共知识图谱。

## 8. 部署后核验

### 8.1 保留业务表

在 Supabase SQL Editor 中执行：

```sql
select to_regclass('public.profiles') as profiles,
       to_regclass('public.agents') as agents,
       to_regclass('public.conversations') as conversations,
       to_regclass('public.messages') as messages,
       to_regclass('public.papers') as papers,
       to_regclass('public.paper_reports') as paper_reports,
       to_regclass('public.research_artifacts') as research_artifacts,
       to_regclass('public.activities') as activities,
       to_regclass('public.catalog_resources') as catalog_resources,
       to_regclass('public.knowledge_nodes') as knowledge_nodes,
       to_regclass('public.knowledge_edges') as knowledge_edges;
```

所有结果都应为对应表名而不是 `null`。

### 8.2 旧知识库已清理

```sql
select to_regclass('public.kb_collections') as kb_collections,
       to_regclass('public.kb_documents') as kb_documents,
       to_regclass('public.kb_chunks') as kb_chunks,
       to_regclass('public.kb_ingestion_jobs') as kb_ingestion_jobs,
       to_regclass('public.kb_retrievals') as kb_retrievals,
       to_regclass('public.kb_citations') as kb_citations;

select id, name, public
from storage.buckets
where id = 'knowledge-base';
```

六个 `to_regclass` 结果应为 `null`，bucket 查询应返回 0 行。

### 8.3 论文存储仍存在

```sql
select id, name, public, file_size_limit
from storage.buckets
where id = 'papers';
```

预期返回一行且 `public = false`。

### 8.4 公开资料与知识图谱

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
```

只验证结构和符合当前种子迁移的内容，不要依赖未经版本化的手工数据量。

### 8.5 后端检查

在配置真实 Supabase 后运行：

```powershell
Set-Location .\backend
python .\scripts\verify_supabase.py
python -m unittest discover -s tests -p "test_*.py" -v
```

`verify_supabase.py` 应只检查保留的 Auth/业务结构，不再要求任何 `kb_*` 表或 `knowledge-base` bucket。

## 9. 业务数据维护

- 用户通过 SciPilot API 创建资料，不需要直接编辑表。
- 公共资料或图谱种子应通过新的编号迁移维护，并使用稳定标识和幂等 `upsert`。
- 只保存获授权的论文原件；公开目录可保存题录、摘要和官方链接，但需遵守来源许可。
- 删除论文时，后端应同时删除 `papers` 表记录、相关报告和对应 Storage 对象。
- 数据库备份不包含 ChatDoc 远端文档；知识库恢复计划还需要保存本地 `KnowledgeBase/Papers/` 原件和上传清单。

## 10. 密钥安全

- 不得把 `.env`、服务端密钥、数据库密码或日志中的鉴权头提交到 GitHub。
- 不得在任何 `VITE_*` 变量中放置 Supabase Secret/Service Role Key。
- Git 提交前检查暂存区和历史，不只检查工作区。
- 长期密钥一旦出现在聊天、截图、Issue 或提交记录中，应立即轮换。
- 测试环境与生产环境使用不同项目、不同密钥和最小权限配置。

## 11. 应提交与禁止提交

应提交：

```text
supabase/migrations/*.sql
backend/.env.example
backend/services/supabase_service.py
backend/scripts/verify_supabase.py
docs/DATABASE_GUIDE.md
```

禁止提交：

```text
backend/.env
frontend/.env
数据库导出中的用户私密数据
Storage 下载缓存
Supabase Secret/Service Role Key
```

# SciPilot 知识库使用与验收

## 当前项目状态

当前 Supabase 项目已经成功执行 `006`、`007`、`008`。数据库中现有：

- 1 个 `public + system_managed` 软件工程公共知识集合。
- 12 篇 `ready` 知识文档和 12 个可检索分块。
- 7 条公共科研目录、15 个知识节点、14 条知识关系。
- 5 个已接入知识检索的公开智能体。

下面的迁移步骤用于在新 Supabase 项目中复现，当前项目不需要重复执行。

## 部署顺序

在 Supabase Dashboard 的 SQL Editor 中，按顺序完整执行：

1. `supabase/migrations/006_workspace_data_layer.sql`
2. `supabase/migrations/007_seed_public_research_catalog.sql`
3. `supabase/migrations/008_knowledge_base.sql`

每个文件必须显示 `Success` 后再执行下一个。SQL 中不需要填写
Publishable Key 或 Secret Key。

## 本地启动

双击仓库根目录的 `启动_SciPilot本地网页_双击运行.cmd`，然后打开：

- 应用：<http://127.0.0.1:5173/>
- API 文档：<http://127.0.0.1:8000/docs>

登录后，从左侧菜单进入“知识库”。

## 已实现的知识库功能

- 创建个人知识库集合。
- 上传最大 25 MiB 的 PDF、TXT、MD/Markdown。
- 直接粘贴文本并保存可选来源 URL。
- 提取文本、SHA-256 去重、分段切块、记录 token 估算值。
- PostgreSQL 全文检索和 `pg_trgm` 中文模糊检索。
- 配置 1536 维 Embeddings 后启用 pgvector 混合检索。
- 显示命中文档、片段、分数和来源信息。
- 根据命中片段回答，并返回可追溯的文档/切块引用。
- 保存检索与引用快照，支持后续审计。
- 删除文档时同时删除数据库切块和私有 Storage 原文件。
- 公共集合和个人集合的数据隔离；检索 RPC 仅后端可执行。
- 系统公共知识可供所有登录用户读取，但普通用户不能写入、更新或删除。
- 五个功能页都能调用对应智能体，并展示知识命中、回答、来源片段和链接。
- 智能体问答与会话问答都会保存检索和引用审计记录。
- 未配置 LLM 时返回带 `[n]` 引用的证据摘录；无证据时明确拒绝编造。

扫描版 PDF 目前不执行 OCR；请先把扫描件转换成可复制文本的 PDF。

## 已授权的软件工程种子知识

`backend/scripts/seed_software_engineering_kb.py` 会幂等写入 12 条知识，覆盖：

- Transformer、BERT、CodeBERT/GraphCodeBERT、SWE-bench 的题录与原创精读卡。
- SWEBOK 需求拆解、NIST SSDF 安全开发、GitHub Actions CI/CD。
- 软件工程可复现实验、CodeSearchNet、Defects4J、ISTQB 测试设计。
- NIST 工程统计导向的结果分析。

每条数据都有 `source_url`、`official_sources`、`license_scope`、`topics`、
`agent_categories` 和 `content_policy`。系统只保存题录、官方链接和 SciPilot
原创中文摘要，不复制受版权保护的论文、标准或数据集全文。

需要在新数据库重新写入时运行：

```powershell
python backend/scripts/seed_software_engineering_kb.py
```

若 `profiles` 不止一条，先在后端环境变量中设置 `SCIPILOT_SEED_USER_ID`；
它只是公共集合的技术所有者，不改变所有登录用户的读取权限。

## 无向量密钥时

不填写 `EMBEDDING_API_KEY` 也能使用知识库。系统会显示
`full-text`，使用全文检索和中文模糊检索。

如需语义检索，在 `backend/.env` 中配置：

```dotenv
EMBEDDING_API_KEY=your_embedding_key
EMBEDDING_BASE_URL=
EMBEDDING_MODEL=text-embedding-3-small
```

模型输出必须为 1536 维。环境变量修改后需重启后端。

## 亲自验收

1. 使用真实邮箱注册并点击确认邮件；若返回 429，等待邮件限额恢复或配置自有 SMTP。
2. 登录并进入“知识库”，确认能看到“软件工程公开知识入门”和 12 篇文档。
3. 依次进入论文精读、问题拆解、实验规划、代码复现、结果分析页面。
4. 在每页“知识库智能体”中提问，确认出现“已命中知识库”、`[1]` 引用和来源卡片。
5. 创建集合“我的测试知识库”。
6. 用“添加文本”写入：

   ```text
   SciPilot 知识库支持 PDF、TXT 和 Markdown。
   未配置向量模型时使用 PostgreSQL 全文与中文模糊检索。
   ```

7. 搜索“中文模糊检索”，应出现刚才的文本及来源片段。
8. 切换“基于来源问答”，询问“没有向量密钥还能检索吗？”，答案应引用该文本。
9. 上传一个可提取文本的 PDF 或 Markdown，确认状态为 `ready` 且切块数大于 0。
10. 重复上传同一文件，页面应提示“已存在”，不会产生第二份文档。
11. 删除测试文档，刷新后确认文档与搜索结果均消失。
12. 使用第二个账号确认看不到第一个账号的私有数据，但仍能读取系统公共知识。

## 常见问题

- `409 / 需要迁移 008`：尚未执行 `008_knowledge_base.sql`。
- `429 / 注册请求过于频繁`：Supabase 默认邮件发送限额；等待恢复或配置 SMTP。
- `请先完成邮箱验证`：在验证邮件中确认后再登录。
- `未提取到文本`：PDF 是扫描图片，当前版本需要先 OCR。
- `Embedding 维度不是 1536`：更换模型，或单独设计新的向量列迁移。
- 搜索无结果：确认文档为 `ready`，并先用文档中的原词测试。

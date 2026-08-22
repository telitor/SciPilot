# SciPilot GitHub 更新与发布清单

> [!NOTE]
> **文档状态：历史版本发布清单。** 本文只对应“仪表盘微调模型对话 + 星火 ChatDoc 外接知识库”那次更新；已于 2026-08-14 复核并退出当前整仓交接/验收口径。当前任务与剩余风险以 [`SciPilot_近期工作交接报告_2026-08-14.docx`](../SciPilot_近期工作交接报告_2026-08-14.docx) 为准。

本清单用于本次“仪表盘微调模型对话 + 星火 ChatDoc 外接知识库”版本。仓库已经是 Git 工作区，应基于当前 `main` 提交增量变更，不使用会丢失历史的目录覆盖或强制重置。

## 1. 功能文件

提交前确认以下实现存在且已经过测试：

```text
backend/
  api/
    routes.py
    schemas.py
  services/
    finetuned_model_service.py
    xunfei_knowledge_base_service.py
    supabase_service.py
  tests/
    test_finetuned_model_service.py
    test_xunfei_knowledge_base_service.py
    test_dashboard_chat_routes.py

frontend/src/
  features/model-chat/
    DashboardModelChat.tsx
    model-chat.css
    index.ts
  pages/
    Dashboard/index.tsx
    KnowledgeBase/index.tsx
  services/api.ts
  types/index.ts

KnowledgeBase/
  api-python-demo/
  api-java-demo/
  星火知识库后端接入说明.md

supabase/migrations/
  009_remove_legacy_knowledge_base.sql

docs/
  FRONTEND_TECH_DEPENDENCIES.md
  DATABASE_GUIDE.md
  GITHUB_UPDATE_CHECKLIST.md

README.md
```

`KnowledgeBase/Papers/` 是本地论文原件目录。是否继续版本化其中的大文件应遵循仓库现有策略和论文许可；不要因为远端 ChatDoc 上传成功就删除本地唯一原件。

## 2. 旧 Supabase 知识库清理

确认应用代码不再引用以下旧结构：

```text
kb_collections
kb_documents
kb_chunks
kb_ingestion_jobs
kb_retrievals
kb_citations
search_knowledge_base(...)
knowledge-base Storage bucket
```

仓库中应移除旧 Supabase RAG 专用的服务、脚本、测试和文档；保留 Supabase Auth、用户/论文/会话/研究产物/活动、`papers` bucket，以及 `knowledge_nodes` / `knowledge_edges` 知识图谱。

当前仓库已移除旧 `008_knowledge_base.sql`，避免新项目部署淘汰的 Supabase RAG；由新的 `009_remove_legacy_knowledge_base.sql` 幂等清理曾执行旧迁移的现有部署。编号缺少 `008` 是有意的。

## 3. 文档清理

以下旧资料描述 Supabase 自建知识库，不应继续发布：

```text
docs/KNOWLEDGE_BASE_GUIDE.md
docs/XFYUN_CHATDOC_BACKEND_INTEGRATION.md
docs/SciPilot知识库与数据库实施交付说明.docx
docs/.gitkeep
```

知识库说明统一到 `KnowledgeBase/星火知识库后端接入说明.md`；前端依赖统一到 `docs/FRONTEND_TECH_DEPENDENCIES.md`。

## 4. 不得提交

```text
backend/.env
frontend/.env
**/.xfyun-upload-state.json
frontend/node_modules/
frontend/dist/
backend/.venv/
__pycache__/
*.pyc
*.log
.repo-sync/
work/
```

此外不得提交：

- MaaS APIKey、ChatDoc APISecret 或 Supabase Secret/Service Role Key；
- 含真实鉴权头、签名或令牌的截图、日志和测试夹具；
- 本地测试账号密码；
- 为调试复制出的论文临时文件。

Model ID、Resource ID 和 Repo ID 虽不是等同于 APISecret 的签名密钥，也应优先通过后端环境变量配置，不写入前端。

## 5. 自动检查

### 后端

```powershell
Set-Location .\backend
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall api services
```

### 前端

```powershell
Set-Location ..\frontend
npm ci
npm run type-check
npm run lint
npm run build
```

### Git 与秘密扫描

从仓库根目录执行：

```powershell
git status --short
git diff --check
git diff --stat
git diff -- . ':(exclude)KnowledgeBase/Papers/**'
```

再使用 `rg` 检查常见敏感字段是否只出现在 `.env.example` 的空占位和文档变量名中：

```powershell
rg -n --hidden --glob '!backend/.env' --glob '!frontend/.env' --glob '!**/.git/**' `
  'APISecret|API_KEY|SECRET_KEY|Bearer ' .
```

检查结果需要人工阅读，不能只按“有匹配/无匹配”判断：代码中的环境变量名称是正常的，真实长值和硬编码 `Authorization` 才需要阻断发布。

## 6. 手工验收

1. 启动 FastAPI 和 Vite，访问 `http://127.0.0.1:5173`。
2. 注册/登录后确认首先进入 `/dashboard`。
3. 仪表盘对话框比例、折叠、移动端布局不遮挡原有内容。
4. 连续发送两轮问题，确认后端收到多轮历史，回答可渲染 Markdown。
5. 开关“论文增强”，确认开启时返回论文引用，关闭时仍可直接对话。
6. 打开 `/knowledge`，核对远端文档数、已向量化数、检索与问答。
7. 断开 MaaS 或 ChatDoc，确认前端显示可理解的错误而不是密钥/上游响应体。
8. 以两个账号验证论文、会话与研究产物所有权隔离。
9. 打开浏览器开发者工具，确认所有请求只发往 FastAPI 和非敏感外链，响应中无上游凭据。

## 7. Supabase 迁移验收

在目标 Supabase 项目执行最新迁移后：

- `kb_*` 表和旧检索函数不存在；
- `knowledge-base` bucket 不存在；
- `profiles`、`agents`、`conversations`、`messages`、`papers`、`paper_reports`、`research_artifacts`、`activities` 均存在；
- `catalog_resources`、`knowledge_nodes`、`knowledge_edges` 仍存在；
- `papers` bucket 存在且为私有。

具体 SQL 见 [DATABASE_GUIDE.md](DATABASE_GUIDE.md)。

## 8. 提交与推送

确认所有检查通过后：

```powershell
git add -A
git status --short
git diff --cached --check
git diff --cached --stat
git commit -m "feat: add MaaS dashboard chat and Spark knowledge base"
git push origin main
```

`git add -A` 会包含删除记录，因此必须在提交前逐项检查暂存区。不要使用 `git push --force`。

推送后在 GitHub 网页检查：

- 最新提交和 CI 状态；
- `.env`、上传断点、构建产物和真实凭据没有出现；
- 新增/删除文件与本清单一致；
- README 的相对链接可打开。

## 9. 凭据轮换

任何在聊天、截图、Issue 或本地共享记录中展示过的长期凭据，都应在推送和生产验收前轮换：

1. 在讯飞控制台生成/更新 MaaS 与 ChatDoc 凭据。
2. 更新本地和部署环境的 Secret，不修改仓库示例值。
3. 重新执行模型状态、知识库状态和真实对话测试。
4. 废止旧凭据并确认其不能继续调用服务。

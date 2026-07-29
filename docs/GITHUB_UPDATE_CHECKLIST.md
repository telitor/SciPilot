# SciPilot GitHub 更新清单

请把下列文件合并到现有 `telitor/SciPilot` 仓库，而不是用当前本地文件夹
整体覆盖远端。当前工作目录没有远端仓库中的 `README.md` 和 `Agent/` 文档，
整体覆盖可能误删原文件。

## 必须提交

```text
.gitignore

backend/
  main.py
  requirements.txt
  .env.example
  api/
    __init__.py
    dependencies.py
    routes.py
    schemas.py
  services/
    supabase_service.py
    knowledge_base_service.py
    agent_knowledge_service.py
    llm_service.py
    xunfei_agent_service.py
  scripts/
    verify_supabase.py
    seed_software_engineering_kb.py
    e2e_knowledge_base.py
    e2e_agent_knowledge.py
  tests/
    test_knowledge_base_service.py
    test_agent_knowledge_service.py

supabase/
  migrations/
    006_workspace_data_layer.sql
    007_seed_public_research_catalog.sql
    008_knowledge_base.sql

frontend/src/
  App.tsx
  services/api.ts
  store/authStore.ts
  types/index.ts
  components/
    Sidebar.tsx
    AgentKnowledgePanel.tsx
  pages/
    Login/index.tsx
    Register/index.tsx
    Dashboard/index.tsx
    Profile/index.tsx
    PaperLibrary/index.tsx
    PaperRead/index.tsx
    ResearchDecompose/index.tsx
    ExperimentRoadmap/index.tsx
    CodeReproduce/index.tsx
    ResultAnalyze/index.tsx
    KnowledgeBase/index.tsx
    KnowledgeGraph/index.tsx

docs/
  DATABASE_GUIDE.md
  KNOWLEDGE_BASE_GUIDE.md
  GITHUB_UPDATE_CHECKLIST.md
  SciPilot知识库与数据库实施交付说明.docx
```

如果当前 GitHub 分支没有 001–005，也应保留并提交
`supabase/migrations/001_*.sql` 到 `005_*.sql`。

## Windows 本地验收文件

```text
启动_SciPilot本地网页_双击运行.cmd
frontend/提供_SciPilot前端静态网页服务.py
docs/SciPilot知识库与数据库实施交付说明.docx
```

这些文件方便 Windows 本地试用和项目交接。本次用户要求交付 Word，因此
`docs/SciPilot知识库与数据库实施交付说明.docx` 应随本次更新提交。

## 不得提交

```text
backend/.env
frontend/.env
.repo-sync/
work/
frontend/node_modules/
frontend/dist/
__pycache__/
*.pyc
*.log
```

尤其不要提交 Supabase Secret Key。该 Secret 已经通过聊天传输，完成联调后应在
Supabase Dashboard 中轮换，并同步更新本地/部署环境变量。

## 新增目录

需要在现有仓库中新建：

- `backend/api/`
- `backend/scripts/`
- `backend/tests/`
- `frontend/src/pages/KnowledgeBase/`

`supabase/migrations/` 和 `docs/` 在原仓库已有；只需在其中增加文件。

## 保留与清理原则

- 保留远端 `README.md`、`Agent/`、001–005 迁移和原有前后端功能。
- 删除未被任何页面引用、且依赖旧 `agentAPI/chat` 合同而导致构建失败的
  `frontend/src/components/AgentChatPanel.tsx`；由 `AgentKnowledgePanel.tsx` 和现有模块页面承担知识问答。
- 不提交旧版 `docs/SciPilot数据库实施与测试交付说明.docx`；以知识库版交付文档为准。
- 不提交 `frontend/dist`、`node_modules`、`.repo-sync`、`work` 或临时验收账户数据。
- 不因当前环境未配置外部模型密钥而删除既有 Agent 代码；知识库证据降级仍可运行。

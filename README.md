# SciCopilot

> 面向软件工程学科的智能体协作学习与项目辅助平台。  
> SciCopilot aims to build an AI-powered vertical platform for Software Engineering, providing specialized agents for learning, coding, project planning, and future knowledge-base assisted workflows.

---

## 1. Project Overview

SciCopilot 是一个面向软件工程学科的垂直领域智能平台。项目目标是为软件工程学习、课程项目开发、代码理解、需求分析、项目规划等场景提供多个专业智能体。

第一版目标不是一次性完成复杂多智能体系统，而是先完成一个可运行的基础功能版：

```text
用户注册 / 登录
    ↓
查看智能体列表
    ↓
选择一个智能体
    ↓
开始对话
    ↓
保存聊天记录
    ↓
再次登录后查看历史对话
```

本项目当前处于 `v0.1 MVP` 开发阶段。

---

## 2. MVP Goal

第一版 SciCopilot 的核心目标：

- 支持用户注册、登录、退出登录
- 展示软件工程方向的智能体列表
- 支持用户选择智能体并发起对话
- 支持调用大模型生成回复
- 支持保存用户消息和 AI 回复
- 支持查看历史对话记录
- 支持基础的数据权限控制，保证用户只能访问自己的数据

---

## 3. Tech Stack

### Frontend

- React / Next.js
- TypeScript
- Tailwind CSS
- Supabase Client SDK

### Backend

- FastAPI
- Python
- Supabase Python Client
- LLM API

### Database & Auth

- Supabase
- PostgreSQL
- Supabase Auth
- Row Level Security
- Supabase Storage

### Dev Tools

- Git / GitHub
- VS Code
- Postman / Apifox
- Supabase Studio
- Supabase CLI

---

## 4. System Architecture

```text
Frontend
  |
  |  User login / Agent list / Chat page
  v
Supabase Auth
  |
  |  User identity
  v
FastAPI Backend
  |
  |  Chat request / LLM call / Business logic
  v
LLM API
  |
  |  AI response
  v
Supabase PostgreSQL
  |
  |  Save conversations and messages
  v
Frontend Display
```

第一版采用：

```text
Supabase + FastAPI + LLM API
```

其中：

- Supabase 负责用户登录、数据库、权限控制和文件存储
- FastAPI 负责后端接口、大模型调用和智能体逻辑
- 前端负责页面展示、用户交互和接口调用

---

## 5. MVP Features

### 5.1 User Module

- 用户注册
- 用户登录
- 用户退出
- 获取当前登录用户信息

### 5.2 Agent Module

第一版预设 3 个智能体：

1. 软件工程学习助手  
   用于解释软件工程课程知识，例如需求分析、UML、软件测试、项目管理等。

2. 代码解释助手  
   用于解释代码逻辑、分析报错、给出修改建议。

3. 项目规划助手  
   用于帮助用户拆解项目功能、规划技术路线、设计数据库和接口。

### 5.3 Chat Module

- 创建新对话
- 发送用户消息
- 调用 AI 生成回复
- 保存用户消息
- 保存 AI 回复
- 查看单个对话的历史消息

### 5.4 History Module

- 查看用户历史对话列表
- 打开历史对话
- 继续已有对话

### 5.5 Permission Module

- 用户只能访问自己的对话
- 用户只能访问自己的消息
- 用户不能读取其他用户的私有数据

---

## 6. Database Design

### 6.1 profiles

用户资料表，用于保存用户的扩展信息。

| Field | Type | Description |
| --- | --- | --- |
| id | uuid | User ID, linked to Supabase Auth |
| username | text | Username |
| avatar_url | text | User avatar |
| role | text | User role |
| created_at | timestamptz | Created time |

---

### 6.2 agents

智能体表，用于保存平台中的智能体配置。

| Field | Type | Description |
| --- | --- | --- |
| id | uuid | Agent ID |
| name | text | Agent name |
| description | text | Agent description |
| system_prompt | text | System prompt |
| category | text | Agent category |
| is_public | boolean | Whether the agent is public |
| created_at | timestamptz | Created time |

---

### 6.3 conversations

对话表，用于保存用户与某个智能体之间的一次会话。

| Field | Type | Description |
| --- | --- | --- |
| id | uuid | Conversation ID |
| user_id | uuid | Owner user ID |
| agent_id | uuid | Related agent ID |
| title | text | Conversation title |
| created_at | timestamptz | Created time |
| updated_at | timestamptz | Updated time |

---

### 6.4 messages

消息表，用于保存具体的聊天消息。

| Field | Type | Description |
| --- | --- | --- |
| id | uuid | Message ID |
| conversation_id | uuid | Related conversation ID |
| user_id | uuid | Owner user ID |
| role | text | user / assistant / system |
| content | text | Message content |
| created_at | timestamptz | Created time |

---

## 7. Backend API Design

### 7.1 Health Check

```http
GET /
```

用于检查后端服务是否正常运行。

---

### 7.2 Get Agent List

```http
GET /agents
```

返回所有可用智能体。

Example response:

```json
[
  {
    "id": "agent_id",
    "name": "软件工程学习助手",
    "description": "帮助用户学习软件工程课程知识"
  }
]
```

---

### 7.3 Create Conversation

```http
POST /conversations
```

Example request:

```json
{
  "agent_id": "agent_id",
  "title": "新的对话"
}
```

---

### 7.4 Get Conversation List

```http
GET /conversations
```

获取当前用户的历史对话列表。

---

### 7.5 Get Messages

```http
GET /conversations/{conversation_id}/messages
```

获取某个对话中的全部消息。

---

### 7.6 Chat

```http
POST /chat
```

Example request:

```json
{
  "conversation_id": "conversation_id",
  "agent_id": "agent_id",
  "message": "请解释一下软件工程中的需求分析"
}
```

Backend workflow:

```text
1. Receive user message
2. Check user identity
3. Get agent system prompt
4. Save user message
5. Call LLM API
6. Save assistant reply
7. Return assistant reply
```

Example response:

```json
{
  "reply": "需求分析是软件工程中的重要阶段，主要目的是明确系统需要解决什么问题……"
}
```

---

## 8. Project Structure

```text
SciCopilot/
│
├── frontend/
│   ├── app/
│   ├── components/
│   ├── lib/
│   ├── package.json
│   └── README.md
│
├── backend/
│   ├── main.py
│   ├── requirements.txt
│   ├── .env.example
│   └── services/
│       ├── llm_service.py
│       └── supabase_service.py
│
├── supabase/
│   ├── migrations/
│   └── config.toml
│
├── README.md
└── .gitignore
```

---

## 9. Environment Variables

Create a `.env` file in the backend directory.

```env
SUPABASE_URL=your_supabase_project_url
SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
LLM_API_KEY=your_llm_api_key
LLM_BASE_URL=your_llm_base_url
LLM_MODEL=your_model_name
```

Important:

```text
Never commit .env to GitHub.
Never expose service_role key in frontend code.
```

---

## 10. Local Development

### 10.1 Clone Repository

```bash
git clone https://github.com/telitor/SciCopilot.git
cd SciCopilot
```

---

### 10.2 Backend Setup

```bash
cd backend
python -m venv .venv
```

Activate virtual environment:

Windows:

```bash
.venv\Scripts\activate
```

macOS / Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run backend:

```bash
uvicorn main:app --reload
```

---

### 10.3 Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

---

## 11. Development Roadmap

### v0.1 MVP

- [ ] Create Supabase project
- [ ] Create database tables
- [ ] Configure Supabase Auth
- [ ] Add basic RLS policies
- [ ] Create FastAPI backend
- [ ] Implement agent list API
- [ ] Implement chat API
- [ ] Save chat messages
- [ ] Build login page
- [ ] Build agent list page
- [ ] Build chat page
- [ ] Show conversation history

---

### v0.2 Knowledge Base

- [ ] File upload
- [ ] PDF / document parsing
- [ ] Text chunking
- [ ] Embedding generation
- [ ] Vector search
- [ ] RAG-based question answering

---

### v0.3 Multi-Agent System

- [ ] Software engineering tutor agent
- [ ] Code analysis agent
- [ ] Project planning agent
- [ ] Testing assistant agent
- [ ] Agent workflow orchestration
- [ ] LangChain / LangGraph integration

---

### v0.4 Project Workspace

- [ ] User project management
- [ ] Requirement document generation
- [ ] Database design assistant
- [ ] API design assistant
- [ ] Test case generation
- [ ] GitHub repository analysis

---

## 12. Current Status

Current version:

```text
v0.1 MVP Planning & Initial Development
```

Current focus:

```text
Build the basic closed loop:
Login → Agent List → Chat → Save Messages → Conversation History
```

---

## 13. Team Responsibility

### Backend

- Supabase database design
- Supabase Auth configuration
- RLS policy design
- FastAPI API development
- LLM API integration
- Conversation and message storage

### Frontend

- Login and register pages
- Agent list page
- Chat page
- Conversation sidebar
- API integration
- UI interaction

### AI / Agent

- Agent prompt design
- Software engineering domain knowledge organization
- Future RAG design
- Future multi-agent workflow design

---

## 14. License

This project is currently for learning, research, and course project development.

License will be decided later.

---

## 15. Project Vision

SciCopilot 希望从一个简单的智能体聊天平台开始，逐步发展为面向软件工程学习和软件项目开发的垂直领域智能平台。

长期目标包括：

- 帮助学生理解软件工程知识
- 帮助开发者拆解项目任务
- 辅助生成需求文档、设计文档和测试用例
- 支持代码解释、代码审查和项目分析
- 构建多个专业智能体协作的 AI 软件工程助手平台

<div align="center">

<img width="100%" src="https://capsule-render.vercel.app/api?type=waving&height=260&color=0:0F172A,40:1D4ED8,70:7C3AED,100:EC4899&text=SciPilot&fontSize=78&fontColor=FFFFFF&animation=fadeIn&fontAlignY=38&desc=AI-powered%20Research%20Agent%20Platform%20for%20Software%20Engineering&descAlignY=58&descSize=18" />

<img src="https://readme-typing-svg.demolab.com?font=Orbitron&size=28&duration=2800&pause=700&color=38BDF8&center=true&vCenter=true&width=900&lines=AI+Research+Agent+Platform;Paper+Reading+%C2%B7+Structured+Analysis+%C2%B7+Intelligent+Q%26A;Built+with+React+%2B+FastAPI+%2B+Supabase;Designed+for+Software+Engineering+Research" />

<br/>

<img src="https://img.shields.io/badge/Status-MVP%20Closed--Loop-7C3AED?style=for-the-badge&logo=rocket&logoColor=white" />
<img src="https://img.shields.io/badge/Core%20Agent-Paper%20Reading-06B6D4?style=for-the-badge&logo=openai&logoColor=white" />
<img src="https://img.shields.io/badge/Frontend-React%20%2B%20TypeScript-2563EB?style=for-the-badge&logo=react&logoColor=white" />
<img src="https://img.shields.io/badge/Backend-FastAPI-059669?style=for-the-badge&logo=fastapi&logoColor=white" />
<img src="https://img.shields.io/badge/Database-Supabase-16A34A?style=for-the-badge&logo=supabase&logoColor=white" />

<br/><br/>

<img src="https://skillicons.dev/icons?i=react,ts,vite,tailwind,py,fastapi,supabase,postgres,github,vscode" />

</div>

---

## ✨ Overview

**SciPilot** is an AI-powered research agent platform designed for **Software Engineering** scenarios.

It integrates **paper reading**, **structured analysis**, **intelligent Q&A**, **conversation management**, and **database persistence** into a unified research workflow. The current MVP focuses on the first core agent: **Paper Reading Agent**, enabling a closed-loop process from PDF upload to AI-assisted paper understanding.

> SciPilot is not a general chatbot.  
> It is a domain-oriented AI research copilot for software engineering learning and research.

---

## 🚀 Core Workflow

```mermaid
flowchart LR
    A[User Login] --> B[Upload PDF Paper]
    B --> C[Backend Extracts Text]
    C --> D[Paper Reading Agent]
    D --> E[Structured Paper Report]
    E --> F[Frontend Visualization]
    F --> G[Paper-based Q&A]
    G --> H[Conversation Saved to Supabase]
```

---

## 🧠 Key Features

<table>
<tr>
<td width="50%">

### 📄 Paper Reading Agent

- PDF paper upload
- Text extraction
- Structured paper analysis
- Research background summary
- Core method explanation
- Experiment result extraction
- Key conclusion generation

</td>
<td width="50%">

### 💬 Intelligent Paper Q&A

- Ask questions based on current paper
- Context-aware paper discussion
- Agent-powered responses
- User / assistant message persistence
- Conversation-based interaction

</td>
</tr>

<tr>
<td width="50%">

### 🔐 Secure Authentication

- Supabase Auth login
- Token-based backend authorization
- Protected conversation APIs
- User-level data isolation

</td>
<td width="50%">

### 🧩 Extensible Agent Platform

- Paper Reading Agent
- Code Explanation Agent
- Project Planning Agent
- Future multi-agent collaboration

</td>
</tr>
</table>

---

## 🏗️ Architecture

```mermaid
flowchart TB
    subgraph Frontend["Frontend Layer"]
        F1["React"]
        F2["TypeScript"]
        F3["Vite"]
        F4["Tailwind CSS"]
    end

    subgraph Backend["Backend Layer"]
        B1["FastAPI"]
        B2["Auth APIs"]
        B3["Paper Analyze API"]
        B4["Chat API"]
    end

    subgraph Database["Supabase Layer"]
        S1["Supabase Auth"]
        S2["PostgreSQL"]
        S3["Row Level Security"]
        S4["Conversations & Messages"]
    end

    subgraph Agent["Agent Layer"]
        A1["Paper Reading Agent"]
        A2["Structured Analysis"]
        A3["Intelligent Q&A"]
    end

    Frontend --> Backend
    Backend --> Database
    Backend --> Agent
    Agent --> Backend
    Backend --> Frontend
```

---

## ⚙️ Tech Stack

| Layer | Technologies |
|---|---|
| Frontend | React, TypeScript, Vite, Tailwind CSS, Zustand, Axios |
| Backend | Python, FastAPI, Uvicorn, Pydantic |
| Database | Supabase PostgreSQL |
| Authentication | Supabase Auth |
| Permission | Row Level Security |
| Agent Service | Backend-proxied Paper Reading Agent |
| Document Processing | PDF Text Extraction |

---

## 🧬 Current MVP Closed Loop

```text
Login
  ↓
Upload PDF
  ↓
Analyze Paper
  ↓
Generate Structured Report
  ↓
Ask Paper-related Questions
  ↓
Agent Replies
  ↓
Save Messages
  ↓
Display Conversation
```

### Current Capabilities

| Module | Status |
|---|---|
| Project Structure | ✅ Completed |
| Supabase Schema | ✅ Completed |
| RLS Policies | ✅ Completed |
| FastAPI Backend | ✅ Completed |
| Auth APIs | ✅ Completed |
| Agent List API | ✅ Completed |
| Conversation APIs | ✅ Completed |
| Message Persistence | ✅ Completed |
| Paper Reading Agent | ✅ Integrated |
| PDF Upload | ✅ MVP Completed |
| Paper Analysis | ✅ MVP Completed |
| Paper Q&A | ✅ MVP Completed |
| Re-upload Paper | ✅ MVP Completed |
| Frontend-Backend Loop | ✅ Running Locally |

---

## 🔌 API Overview

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Health check |
| `POST` | `/auth/login` | User login |
| `POST` | `/auth/register` | User registration |
| `GET` | `/users/me` | Current user |
| `GET` | `/agents` | Get agent list |
| `POST` | `/conversations` | Create conversation |
| `GET` | `/conversations` | List conversations |
| `GET` | `/conversations/{conversation_id}/messages` | List messages |
| `POST` | `/chat` | Agent chat |
| `POST` | `/papers/analyze` | Analyze uploaded paper |

---

## 🗂️ Database Model

```mermaid
erDiagram
    profiles {
        uuid id
        text email
        text username
        text avatar_url
        timestamptz created_at
        timestamptz updated_at
    }

    agents {
        uuid id
        text name
        text description
        text category
        text system_prompt
        boolean is_public
        timestamptz created_at
        timestamptz updated_at
    }

    conversations {
        uuid id
        uuid user_id
        uuid agent_id
        text title
        timestamptz created_at
        timestamptz updated_at
    }

    messages {
        uuid id
        uuid conversation_id
        uuid user_id
        text role
        text content
        timestamptz created_at
    }

    profiles ||--o{ conversations : owns
    agents ||--o{ conversations : powers
    conversations ||--o{ messages : contains
```

---

## 📁 Project Structure

```text
SciPilot
├── Agent
│   └── PaperReading.md
│
├── backend
│   ├── main.py
│   ├── requirements.txt
│   ├── .env.example
│   └── services
│       ├── supabase_service.py
│       ├── llm_service.py
│       └── xunfei_agent_service.py
│
├── frontend
│   ├── public
│   ├── src
│   │   ├── components
│   │   ├── pages
│   │   ├── services
│   │   ├── store
│   │   └── main.tsx
│   ├── package.json
│   ├── vite.config.ts
│   └── .env.example
│
├── supabase
│   └── migrations
│       ├── 001_init_schema.sql
│       ├── 002_updated_at_trigger.sql
│       └── 003_rls_policies.sql
│
├── docs
├── .gitignore
└── README.md
```

---

## 🖥️ Local Development

### 1. Clone Repository

```bash
git clone https://github.com/telitor/SciPilot.git
cd SciPilot
```

---

### 2. Start Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn main:app --reload
```

Backend:

```text
http://localhost:8000
```

Swagger:

```text
http://localhost:8000/docs
```

---

### 3. Start Frontend

```bash
cd frontend
npm install
copy .env.example .env
npm run dev
```

Frontend:

```text
http://localhost:5173
```

---

## 🔑 Environment Variables

### Backend `.env`

```env
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key

XF_AGENT_APP_ID=your_app_id
XF_AGENT_API_KEY=your_api_key
XF_AGENT_API_SECRET=your_api_secret
XF_AGENT_ASSISTANT_ID=your_assistant_id
```

### Frontend `.env`

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_SUPABASE_URL=your_supabase_url
VITE_SUPABASE_ANON_KEY=your_supabase_anon_key
```

---

## 🛡️ Security Design

```mermaid
flowchart LR
    A[Frontend] -->|Only anon key| B[FastAPI Backend]
    B -->|Service role key| C[Supabase]
    B -->|Agent secret| D[Paper Reading Agent]
    A -. forbidden .-> D
    A -. forbidden .-> C
```

- Frontend never stores service role key.
- Frontend never stores Agent API Key or Secret.
- All sensitive keys stay in `backend/.env`.
- Agent calls are proxied by FastAPI.
- Supabase RLS protects user data.

---

## 🧭 Roadmap

```mermaid
timeline
    title SciPilot Development Roadmap

    MVP
      : User Login
      : PDF Upload
      : Paper Analysis
      : Paper Q&A
      : Message Persistence

    Next
      : Paper History
      : Long-term Paper Context
      : Better JSON Stabilization
      : More Robust PDF Parsing

    Future
      : Multi-Agent Collaboration
      : Code Explanation Agent
      : Experiment Reproduction Agent
      : Literature Review Agent
      : Knowledge Graph
      : Cloud Deployment
```

---

## 🌌 Vision

SciPilot aims to become a specialized AI research copilot for software engineering students, researchers, and developers.

It focuses on:

- understanding research papers,
- organizing research knowledge,
- supporting paper-based conversations,
- connecting AI agents with real workflows,
- and building a scalable multi-agent research platform.

---

<div align="center">

<img width="100%" src="https://capsule-render.vercel.app/api?type=waving&height=150&color=0:EC4899,40:7C3AED,70:2563EB,100:0F172A&section=footer" />

<h3>🚀 SciPilot · AI Research Copilot for Software Engineering</h3>

<strong>From paper reading to intelligent research workflows.</strong>

</div>

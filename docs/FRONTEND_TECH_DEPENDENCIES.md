# SciPilot 前端技术依赖清单

本文按当前仓库实际代码与 `frontend/package.json` 汇总前端运行环境、第三方库、外部服务和本地命令。版本范围以 `package.json` 为准，精确安装版本以 `frontend/package-lock.json` 为准。

## 1. 运行环境结论

| 环境 | 是否需要 | 建议版本 | 用途 |
| --- | --- | --- | --- |
| 浏览器 | 必需 | 当前稳定版 Chrome / Edge / Firefox / Safari | 运行 React 单页应用；需支持 ES2020、Fetch/Promise、`localStorage` 和现代 CSS |
| Node.js | 前端开发与构建必需 | 18+，推荐当前 LTS | 安装依赖、运行 Vite、TypeScript、ESLint 和构建命令 |
| npm | 必需（默认包管理器） | 9+ | 仓库提交了 `package-lock.json`，建议使用 `npm ci` 做可复现安装 |
| Python | 仅启动完整项目时必需 | 3.10+，推荐 3.11 | 运行 FastAPI 后端；前端源码本身不依赖 Python |
| Go | 不需要 | 无 | 当前前端、后端和知识库工具均没有 Go 模块或 Go 编译步骤 |
| Java | 前端不需要 | 无 | `KnowledgeBase/api-java-demo/` 仅是可选的 ChatDoc 服务端示例，不参与前端构建 |

前端不是可以脱离后端完整工作的纯静态演示：登录、仪表盘对话、论文、知识库和科研模块都通过 FastAPI 获取真实数据。

## 2. 前端核心技术

| 技术 | 当前版本范围 | 职责 |
| --- | --- | --- |
| React | `^18.2.0` | 组件、Hooks、Strict Mode 和页面渲染 |
| React DOM | `^18.2.0` | 浏览器 DOM 挂载 |
| TypeScript | `^5.3.3` | 类型检查与编译 |
| Vite | `^5.1.4` | 本地开发服务器、代理和生产构建 |
| React Router DOM | `^6.22.0` | `/dashboard`、`/knowledge` 等 SPA 路由与登录保护 |
| Zustand | `^4.5.0` | 登录、聊天、论文和 UI 状态 |
| Axios | `^1.6.7` | 调用 FastAPI、统一 Bearer Token 和错误处理 |
| Tailwind CSS | `^3.4.1` | 现有页面的实用类样式与主题变量 |
| 原生 CSS | 浏览器内置 | 全局设计系统及 `features/model-chat/model-chat.css` 的仪表盘对话样式 |

## 3. 展示与交互库

| 库 | 当前版本范围 | 当前用途 |
| --- | --- | --- |
| `lucide-react` | `^0.344.0` | 页面、导航、状态和对话框图标 |
| `react-markdown` | `^9.0.1` | 渲染模型回答和知识库答案 |
| `remark-gfm` | `^4.0.0` | Markdown 表格、任务列表等 GFM 语法 |
| `echarts` | `^5.5.0` | 实验结果图表引擎 |
| `echarts-for-react` | `^3.0.2` | ECharts 的 React 封装 |
| `rehype-highlight` | `^7.0.0` | 已安装的 Markdown 代码高亮能力；当前核心对话组件未直接启用 |
| `rehype-katex` | `^7.0.0` | 已安装的公式渲染能力；当前核心对话组件未直接启用 |
| `remark-math` | `^6.0.0` | 已安装的 Markdown 数学语法能力；当前核心对话组件未直接启用 |
| `framer-motion` | `^11.0.0` | 已安装的动画能力；当前主要界面动画使用 CSS |
| `clsx` | `^2.1.0` | 已安装的条件类名工具，当前页面未直接引用 |
| `tailwind-merge` | `^2.2.1` | 已安装的 Tailwind 类名合并工具，当前页面未直接引用 |

将“已安装但当前未直接引用”的依赖单独标出，是为了避免把计划能力误写成已经使用的实现。若后续确认不需要这些能力，可以在独立清理提交中移除并重新执行构建测试。

## 4. 开发依赖

| 依赖 | 当前版本范围 | 用途 |
| --- | --- | --- |
| `@vitejs/plugin-react` | `^4.2.1` | Vite React/JSX 转换与开发刷新 |
| `@types/react` | `^18.2.56` | React TypeScript 类型 |
| `@types/react-dom` | `^18.2.19` | React DOM TypeScript 类型 |
| ESLint | `^8.56.0` | 静态检查 |
| `@typescript-eslint/parser` | `^7.0.2` | ESLint 解析 TypeScript |
| `@typescript-eslint/eslint-plugin` | `^7.0.2` | TypeScript 规则 |
| `eslint-plugin-react-hooks` | `^4.6.0` | Hooks 规则 |
| `eslint-plugin-react-refresh` | `^0.4.5` | React Refresh 安全规则 |
| Prettier | `^3.2.5` | TS/TSX/CSS/JSON 格式化 |
| PostCSS | `^8.4.35` | CSS 处理管线 |
| Autoprefixer | `^10.4.17` | 浏览器前缀 |

## 5. 外部网站与 API

### 浏览器会访问

| 地址 | 是否核心 | 用途与数据 |
| --- | --- | --- |
| `http://127.0.0.1:8000/api/v1`（默认） | 是 | 浏览器访问 SciPilot FastAPI；通过 `VITE_API_BASE_URL` 配置 |
| `https://fonts.googleapis.com` / `https://fonts.gstatic.com` | 否 | `frontend/index.html` 加载 Inter 与 JetBrains Mono；离线或受限网络下会回退到系统字体 |
| 用户点击的论文、资料或 GitHub 来源 URL | 否 | 由浏览器新窗口打开；不是前端后台请求 |

### 仅 FastAPI 后端会访问

| 外部服务 | 地址/配置 | 用途 |
| --- | --- | --- |
| 讯飞 MaaS OpenAI 兼容接口 | `SCIPILOT_LLM_BASE_URL`，默认 `https://maas-api.cn-huabei-1.xf-yun.com/v2` | 仪表盘多轮对话与知识增强回答 |
| 讯飞星火 ChatDoc | `XFYUN_KB_BASE_URL`，默认 `https://chatdoc.xfyun.cn` | 远端论文库状态、向量检索、文件管理 |
| Supabase | `SUPABASE_URL` | Auth、业务 PostgreSQL 和 `papers` 私有 Storage |
| 可选通用模型 | `LLM_BASE_URL` | 非核心兼容/降级链路，按后端配置启用 |
| 讯飞 WebSocket Agent | `XF_AGENT_WS_HOST` / `XF_AGENT_WS_PATH` | 现有论文 Agent 的可选兼容链路，不是仪表盘对话的主协议 |

浏览器不会直接访问 MaaS、ChatDoc 或 Supabase，也不应获得其 Secret。这样的代理边界可避免在构建产物和浏览器网络请求中暴露长期凭据。

## 6. 前端环境变量

复制 `frontend/.env.example` 为 `frontend/.env`：

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
VITE_WS_URL=ws://127.0.0.1:8000/ws
```

- 当前核心接口使用 Axios HTTP，`VITE_API_BASE_URL` 是必需配置。
- `VITE_WS_URL` 为现有 WebSocket 能力预留，不参与仪表盘 MaaS HTTP 对话。
- Vite 会把所有 `VITE_*` 值编译进浏览器资源，因此禁止填入 APIKey、APISecret、Resource ID 或 Supabase 服务端密钥。

## 7. 本地命令

以下命令在仓库根目录执行。

### 可复现安装与开发

```powershell
Set-Location .\frontend
npm ci
Copy-Item .env.example .env
npm run dev
```

访问 `http://127.0.0.1:5173`。Vite 开发服务器也把 `/api` 代理到 `http://localhost:8000`、把 `/ws` 代理到 `ws://localhost:8000`。

### 检查与构建

```powershell
npm run type-check
npm run lint
npm run build
npm run preview
```

| 命令 | 结果 |
| --- | --- |
| `npm run dev` | 启动 Vite 开发服务器，默认端口 5173 |
| `npm run type-check` | 执行 `tsc --noEmit` |
| `npm run lint` | ESLint 检查 TS/TSX，警告也视为失败 |
| `npm run format` | Prettier 修改 `src` 下 TS/TSX/CSS/JSON |
| `npm run build` | TypeScript 编译后生成 `frontend/dist/` |
| `npm run preview` | 本地预览 `dist/` |

### 完整本地联调

终端 1：

```powershell
Set-Location .\backend
.\.venv\Scripts\Activate.ps1
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

终端 2：

```powershell
Set-Location .\frontend
npm run dev
```

## 8. 构建产物与提交边界

- 应提交：`package.json`、`package-lock.json`、源码、Vite/Tailwind/PostCSS/TypeScript/ESLint 配置和 `.env.example`。
- 不应提交：`frontend/.env`、`node_modules/`、`dist/`、日志和本机缓存。
- 生产构建输出包含 source map（见 `vite.config.ts` 的 `sourcemap: true`）。若生产环境不希望公开源码映射，应在部署配置中关闭或限制 `.map` 文件访问。
- 当前没有 Go、Docker、Electron、Next.js、Vue、D3.js、Neo4j、MongoDB、MinIO 或前端直连 Supabase 依赖；不要仅凭早期规划文档为这些组件准备环境。

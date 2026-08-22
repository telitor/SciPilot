# SciPilot Frontend

当前前端是 React 18 + TypeScript + Vite 单页应用。登录后首屏 `/dashboard`
包含 SciPilot MaaS 微调模型多轮对话框，并可按需启用星火 ChatDoc 论文知识增强。

浏览器只调用 FastAPI，不直接持有或请求 MaaS、ChatDoc、Supabase 的服务端密钥。

## 本地开发

```powershell
npm ci
Copy-Item .env.example .env
npm run dev
```

默认访问地址：`http://127.0.0.1:5173`。

## 检查与构建

```powershell
npm run type-check
npm run lint
npm run build
```

`npm run build` 会在生产构建后执行 bundle 预算检查：路由页面按需加载，结果图表拆分为独立的 ECharts Core、渲染器和 React 适配层，图表资源不会进入初始 HTML，且任一 JavaScript chunk 不得超过 500 kB。已有 `dist/` 也可用 `npm run verify:bundle` 单独复核。

完整依赖、外部服务、Python/Node/Go 环境说明见
[`../docs/FRONTEND_TECH_DEPENDENCIES.md`](../docs/FRONTEND_TECH_DEPENDENCIES.md)。

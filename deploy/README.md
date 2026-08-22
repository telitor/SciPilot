# SciPilot 生产部署基线

这套基线用两个容器运行 SciPilot：`frontend` 是非 root Nginx，负责 SPA 静态资源和 `/api` 反向代理；`backend` 是单进程 FastAPI/Uvicorn。只对主机发布前端的 `8080` 端口，后端只在 Compose 网络内可见。

## 1. 必备条件

- Docker Engine 24+ 和 Docker Compose v2.20+；
- 一份受限访问的 `deploy/.env`；
- 已应用当前仓库 migration 的 Supabase 项目；
- 一个主机级 TLS 终止器或云负载均衡器。容器默认只绑定 `127.0.0.1:8080`，不直接暴露明文 HTTP。

从仓库根目录开始：

```powershell
Copy-Item deploy/.env.example deploy/.env
# 编辑 deploy/.env，替换占位符，不要把真实密钥写回 .env.example
python deploy/manage.py --env-file deploy/.env preflight
```

Linux 上在预检前限制权限：

```bash
cp deploy/.env.example deploy/.env
chmod 600 deploy/.env
python3 deploy/manage.py --env-file deploy/.env preflight
```

预检会校验必需 Supabase 配置、占位符、CORS/Password Reset HTTPS 地址、Supabase/MaaS/ChatDoc HTTPS 与 Agent WSS 传输、禁用本地演示与 Docker 执行、上传限额、镜像标签、Docker 守护进程和最终 Compose 配置。它只输出变量名和问题，不输出变量值。

## 2. 配置边界

`deploy/.env` 是运行时密钥配置，不会进入镜像层，已被 Git 忽略。生产必须保持：

- `SCIPILOT_ENV=production`；
- `LOCAL_DEMO_MODE=false`；
- `AUTH_AUTO_CONFIRM_EMAIL=false`；
- `SCIPILOT_DOCKER_EXECUTION_ENABLED=false`。该 Web 栈不挂载 Docker socket，受控执行应放到单独审核的 worker 部署中；
- `CORS_ORIGINS` 只填浏览器实际访问的 HTTPS origin，`PASSWORD_RESET_REDIRECT_URL` 必须使用其中一个 origin。

`frontend/nginx.conf` 限制请求体为 32 MiB，因此 `MAX_UPLOAD_MB` 不能超过 32。如要放大，必须同时评估上游 TLS 代理、Nginx 与后端的限额。

后端镜像默认安装 `poppler-utils`、`tesseract-ocr` 和英文语言包，但运行时 `SCIPILOT_PDF_OCR_ENABLED=false` 仍保持 OCR 关闭。在明确不需要 OCR 的环境可同时保持运行时开关关闭并设 `SCIPILOT_INSTALL_OCR=false` 缩小镜像；这不影响 API 启动或文本型 PDF。

## 3. 发布

每次发布使用不可变标签，建议用 12 位 Git SHA。脚本会拒绝重用状态文件已记录或本地镜像已占用的标签，避免覆盖回滚依据。它按锁定依赖构建前后端镜像，启动容器，等待 Compose liveness，再经公开入口验证前端、后端与核心 Supabase readiness，成功后才记录可回滚状态。

```powershell
$tag = git rev-parse --short=12 HEAD
python deploy/manage.py --env-file deploy/.env release --tag $tag
```

当需要刷新基础镜像的安全补丁时，显式加 `--pull`；这会改变构建输入，应经过完整回归。

```powershell
python deploy/manage.py --env-file deploy/.env release --tag $tag --pull
```

发布元数据保存在本机 `deploy/.state/releases.json`，已被 Git 忽略。不要在新版本稳定前删除上一版本的本地镜像。

## 4. 验证、日志与告警接入

随时可运行无外部 AI 调用的健康验证：

```powershell
python deploy/manage.py --env-file deploy/.env verify
```

验证顺序为：

1. `GET /healthz` 检查 Nginx/静态前端容器；
2. `GET /api/v1/health` 经同一入口和反向代理检查 FastAPI liveness；
3. `GET /api/v1/readiness` 用最多数秒的无敏感输出探针验证 Supabase Auth 与迁移管理的核心 `research_projects` 表。

三个端点都必须返回 HTTP 200 和 `{"status":"ok"}`。`verify` 成功返回 0，失败返回非 0。前两个 liveness 端点不调用 Supabase 或外部 AI，因此容器启动冒烟可在无真实 Supabase 的 CI 中执行；`deploy/manage.py verify` 及发布/回滚则必须通过核心 readiness。可选 AI 服务的可用性应使用应用内状态和 AI 运营告警单独监控。

应用日志只写 stdout/stderr，Compose 的 `json-file` 驱动按每个容器 10 MiB × 5 文件轮转：

```powershell
python deploy/manage.py --env-file deploy/.env logs --tail 200
python deploy/manage.py --env-file deploy/.env logs --tail 200 --follow
```

Nginx access log 是单行 JSON，包含请求 ID、耗时和上游耗时，可由 Docker/Vector/Fluent Bit 收集。日志中不应记录 Authorization 头、密钥或上传正文。

## 5. 回滚

默认回滚到脚本记录的上一个成功版本：

```powershell
python deploy/manage.py --env-file deploy/.env rollback
```

也可指定已经存在于本机的不可变标签：

```powershell
python deploy/manage.py --env-file deploy/.env rollback --tag c4d3d60abcde
```

回滚前会先确认前后端两个镜像都存在，切换后重新执行同一健康与 readiness 验证，成功才更新状态。新发布在容器切换或验证阶段失败时，脚本会自动重新激活状态中的最近成功版本，且仍以非 0 退出代码报告本次发布失败。若当次发布引入了数据库变更，不要修改或倒放已应用 migration；应在发布前确认新 migration 向后兼容，必要时另增修复 migration。

## 6. 持久化和恢复边界

- Compose 容器无状态、根文件系统只读；`/tmp` 是有容量上限的 tmpfs，容器重建后清空。
- 用户、项目、论文、任务、产物、实验记录和私有文件的权威副本位于 Supabase Postgres/Storage，不在 Docker volume 中。
- 备份策略由 Supabase 项目负责：启用适合的 PITR/定期数据库备份，并对 `papers` 和 `experiment-results` 私有 bucket 做对应保护。
- 恢复演练应先在隔离的 Supabase 项目中完成：恢复数据库和 Storage，将临时 `deploy/.env` 指向该项目，运行预检和健康验证，再用受控验收账号检查关键数据。
- `deploy/.env` 应由组织的密钥管理器加密备份；`deploy/.state` 只是可重建的发布元数据。

## 7. 安全默认值与扩容注意

两个容器都使用非 root 用户、只读根文件系统、`no-new-privileges`、全部 capability 删除、PID/CPU/内存上限。后端端口不映射到主机，也不挂载 Docker socket。

当后端扩展到多副本时，Supabase lease 可以协调持久任务，但当前限流是进程内实现；必须先在 TLS/网关层加入共享限流，再增加副本。

# PDF 版面证据与实验沙箱

## PDF 解析

`backend/services/pdf_extraction_service.py` 先提取数字文本，并为每页保存 `normalized-top-left` 坐标空间中的轻量文本段。没有数字文本的页面可按需使用 Poppler 渲染和 Tesseract OCR；数字页与扫描页会按原页序合并。报告内容会记录 `extraction_method`、`ocr_page_count` 和 `page_evidence`，因此后续引用可以回到具体页面和坐标。

OCR 默认关闭，避免开发机缺少本地工具时出现隐式行为。生产后端镜像已经包含 Poppler、Tesseract 和英文语言包，可在运行配置中启用：

```dotenv
SCIPILOT_PDF_OCR_ENABLED=true
SCIPILOT_PDF_OCR_LANGUAGES=eng
SCIPILOT_PDF_OCR_DPI=180
SCIPILOT_PDF_OCR_TIMEOUT_SECONDS=25
SCIPILOT_PDF_OCR_MIN_CONFIDENCE=35
```

中文识别需要在镜像中额外安装对应 Tesseract 语言包，并将语言设置为例如 `chi_sim+eng`。页数、字符数、DPI、单页超时和文本段数量均有上限；OCR 子进程不经过 Shell，也不接受任意命令参数。

## 实验沙箱

受控执行仍然是显式启用功能。API 的 `environment` 可选择管理员授权的资源：

```json
{
  "image": "python:3.11-slim",
  "datasets": ["benchmark-2026"],
  "gpu": "0"
}
```

管理员侧配置示例：

```dotenv
SCIPILOT_DOCKER_EXECUTION_ENABLED=true
SCIPILOT_DOCKER_ALLOWED_IMAGES=python:3.11-slim,rocker/r-ver:4.4.1
SCIPILOT_DATASET_MOUNTS_JSON={"benchmark-2026":"/srv/scipilot/datasets/benchmark-2026"}
SCIPILOT_DOCKER_GPU_ENABLED=true
SCIPILOT_GPU_CONCURRENCY=1
SCIPILOT_GPU_QUEUE_WAIT_SECONDS=600
SCIPILOT_EXECUTION_MAX_WORKSPACE_MB=1024
```

- 允许直接运行仓库中的 Python、Pytest、R、Julia 和 Node 脚本，不允许 Shell 管道、重定向、内联代码或密钥形参数。
- 镜像必须精确命中白名单；客户端不能提供宿主机路径。
- 数据集由管理员把 ID 映射到宿主机目录，容器内只读挂载到 `/datasets/<id>`。
- GPU 必须由管理员启用；跨进程锁槽限制同一主机的并发并提供有界等待。
- 正式运行关闭网络，容器为只读根文件系统，并限制 CPU、内存、PID、时间与工作区磁盘用量；超出磁盘配额时会主动终止容器。

生产 Web 基线不会挂载 Docker socket，并保持该能力关闭。需要自动实验时，应把研究任务 worker 部署到经过审核的独立主机，同时让所有 worker 共享 `SCIPILOT_GPU_SLOT_DIR`。

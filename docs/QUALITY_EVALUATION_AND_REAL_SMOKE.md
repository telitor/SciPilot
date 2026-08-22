# 质量评测与真实服务冒烟

SciPilot 的管理员质量页包含三条互补闭环：固定检索用例用于无额度离线回归，真实模型短用例用于链路冒烟，用户反馈只能在人工审核后进入后续处理。

评测运行现在按稳定 suite slug 比较前一次完成结果，即使固定数据集升级了版本也能显示 Recall/MRR、通过率、P95 延迟和已知成本变化。运行记录只保存指标、哈希和诊断，不保存真实模型输出正文。

`.github/workflows/real-provider-smoke.yml` 每周提供一次最多 6 个短用例的部署后检查，但定时运行默认关闭。启用前应建立受限管理员验收账号并配置：

- Repository variable：`SCIPILOT_REAL_SMOKE_ENABLED=true`；
- Actions secrets：`SCIPILOT_SMOKE_BASE_URL`、`SCIPILOT_SMOKE_EMAIL`、`SCIPILOT_SMOKE_PASSWORD`。

也可通过 `workflow_dispatch` 手动运行，但必须勾选会产生外部调用的确认项。工作流先检查同一公网入口的健康端点，再登录并调用数据库中启用的 `real-model-smoke` suite；任何用例失败都会令工作流失败。脚本不会打印访问令牌、密码或模型回复。

日常开发和普通 CI 只运行离线测试，不会调用讯飞 Agent、MaaS 或 ChatDoc，也不会消耗这些平台的额度。

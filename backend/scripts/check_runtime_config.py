"""Validate local runtime configuration without printing credential values."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BACKEND_DIR / ".env"


def _is_set(*names: str) -> bool:
    return any(os.getenv(name, "").strip() for name in names)


def _enabled(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    if not ENV_PATH.is_file():
        print("[ERROR] backend/.env 不存在。")
        return 1

    load_dotenv(ENV_PATH)
    local_demo = (
        os.getenv("SCIPILOT_ENV", "production").strip().lower() == "local"
        and _enabled("LOCAL_DEMO_MODE")
        and _is_set("LOCAL_DEMO_PASSWORD")
    )

    missing: list[str] = []
    if not local_demo:
        if not _is_set("SUPABASE_URL"):
            missing.append("SUPABASE_URL")
        if not _is_set("SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY"):
            missing.append("SUPABASE_PUBLISHABLE_KEY 或 SUPABASE_ANON_KEY")
        if not _is_set("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
            missing.append("SUPABASE_SECRET_KEY 或 SUPABASE_SERVICE_ROLE_KEY")

    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    supabase_host = ""
    if supabase_url:
        parsed = urlparse(supabase_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            missing.append("有效的 SUPABASE_URL")
        else:
            supabase_host = parsed.hostname or ""

    if missing:
        print("[ERROR] 后端配置不完整：" + "，".join(missing))
        print("请编辑 backend/.env，保存后重新运行启动器。")
        return 1

    if supabase_host and not local_demo:
        try:
            socket.getaddrinfo(supabase_host, 443, type=socket.SOCK_STREAM)
        except OSError:
            print("[ERROR] SUPABASE_URL 对应的项目域名无法解析。")
            print("请在 Supabase 项目后台重新复制 Project URL 和 API Keys，再重启后端。")
            return 1

    print("[OK] Supabase/本地演示登录配置已通过检查。")
    print(
        "[OK] MaaS 对话模型已配置。"
        if _is_set("SCIPILOT_LLM_API_KEY", "SCIPILOT_LLM_MODEL_ID")
        else "[WARN] MaaS 对话模型未完整配置，Dashboard 对话将不可用。"
    )
    print(
        "[OK] 星火知识库已配置。"
        if all(
            _is_set(name)
            for name in ("XFYUN_KB_APP_ID", "XFYUN_KB_API_SECRET", "XFYUN_KB_REPO_ID")
        )
        else "[WARN] 星火知识库未完整配置，论文增强将不可用。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Supabase client factories used by the FastAPI backend."""

import os
import threading
import time
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from supabase import Client, ClientOptions, create_client

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class SupabaseConfigurationError(RuntimeError):
    """Raised when required Supabase environment variables are missing."""


class SupabaseReadinessError(RuntimeError):
    """Secret-free signal that the core Supabase dependency is not ready."""


_READINESS_LOCK = threading.Lock()
_READINESS_CACHE_UNTIL = 0.0
_READINESS_CACHE_OK = False


def _required_env(name: str, *aliases: str) -> str:
    for candidate in (name, *aliases):
        value = os.getenv(candidate, "").strip()
        if value:
            return value
    if not value:
        raise SupabaseConfigurationError(
            f"后端尚未读取到 Supabase 配置（{name}）。"
            "请确认配置已保存到 backend/.env，并完全停止旧后端后重新启动。"
        )
    return value


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Return the trusted service-role client.

    This client may bypass RLS and must only be used by the backend after it has
    authenticated the caller and checked row ownership.
    """

    return create_client(
        _required_env("SUPABASE_URL"),
        _required_env("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY"),
        options=ClientOptions(auto_refresh_token=False, persist_session=False),
    )


def get_supabase_auth_client() -> Client:
    """Return an isolated anon-key client for one sign-up/sign-in request."""

    return create_client(
        _required_env("SUPABASE_URL"),
        _required_env("SUPABASE_ANON_KEY", "SUPABASE_PUBLISHABLE_KEY"),
        options=ClientOptions(auto_refresh_token=False, persist_session=False),
    )


def _secure_supabase_url(value: str) -> bool:
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and not parsed.username
        and not parsed.password
        and (port is None or 1 <= port <= 65535)
        and parsed.path in {"", "/"}
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )


def _probe_supabase(timeout_seconds: float) -> None:
    try:
        url = _required_env("SUPABASE_URL")
        if not _secure_supabase_url(url):
            raise SupabaseReadinessError("Core data service is not ready")
        secret = _required_env("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY")
        timeout = httpx.Timeout(timeout_seconds, connect=min(1.0, timeout_seconds))
        with httpx.Client(timeout=timeout, follow_redirects=False) as http_client:
            client = create_client(
                url,
                secret,
                options=ClientOptions(
                    auto_refresh_token=False,
                    persist_session=False,
                    postgrest_client_timeout=timeout,
                    httpx_client=http_client,
                ),
            )
            # Auth and one migration-owned core table are both required for the
            # production application. Responses are discarded and never logged.
            client.auth.admin.list_users(page=1, per_page=1)
            client.table("research_projects").select("id").limit(1).execute()
    except SupabaseReadinessError:
        raise
    except Exception:
        raise SupabaseReadinessError("Core data service is not ready") from None


def check_supabase_readiness(
    *, timeout_seconds: float = 2.0, cache_seconds: float = 5.0
) -> None:
    """Perform a bounded, cached Auth/PostgREST readiness probe.

    No response body, credential, URL, or upstream exception text crosses this
    boundary. A short cache prevents a public readiness probe from amplifying
    traffic to Supabase while still allowing deployment verification to retry.
    """

    timeout = min(5.0, max(0.5, float(timeout_seconds)))
    cache_for = min(30.0, max(0.0, float(cache_seconds)))
    global _READINESS_CACHE_OK, _READINESS_CACHE_UNTIL
    with _READINESS_LOCK:
        now = time.monotonic()
        if now < _READINESS_CACHE_UNTIL:
            if _READINESS_CACHE_OK:
                return
            raise SupabaseReadinessError("Core data service is not ready")
        try:
            _probe_supabase(timeout)
        except SupabaseReadinessError:
            _READINESS_CACHE_OK = False
            # Cache failures briefly so a recovery can be observed promptly.
            _READINESS_CACHE_UNTIL = time.monotonic() + min(cache_for, 2.0)
            raise
        _READINESS_CACHE_OK = True
        _READINESS_CACHE_UNTIL = time.monotonic() + cache_for


def reset_supabase_readiness_cache() -> None:
    """Reset only the process-local readiness cache for isolated tests."""

    global _READINESS_CACHE_OK, _READINESS_CACHE_UNTIL
    with _READINESS_LOCK:
        _READINESS_CACHE_OK = False
        _READINESS_CACHE_UNTIL = 0.0

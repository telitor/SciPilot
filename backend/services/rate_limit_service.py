"""Small process-local limiter for expensive and authentication endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from collections import OrderedDict, deque
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response


@dataclass(frozen=True)
class RateRule:
    name: str
    requests: int
    window_seconds: int


def _positive_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _rule_for(path: str, method: str) -> RateRule | None:
    if method != "POST":
        return None
    if path in {
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/forgot-password",
        "/api/v1/auth/reset-password",
    }:
        return RateRule("auth", _positive_int("RATE_LIMIT_AUTH_REQUESTS", 10), 60)
    if path in {"/api/v1/papers/upload", "/api/v1/papers/upload-async"}:
        return RateRule("upload", _positive_int("RATE_LIMIT_UPLOAD_REQUESTS", 6), 600)
    if path in {"/api/v1/knowledge/search", "/api/v1/knowledge/answer", "/api/v1/knowledge/xunfei/answer"}:
        return RateRule("knowledge", _positive_int("RATE_LIMIT_KNOWLEDGE_REQUESTS", 30), 120)
    model_paths = {
        "/api/v1/chat",
        "/api/v1/dashboard/chat",
        "/api/v1/research/decompose",
        "/api/v1/research/decompose-async",
        "/api/v1/experiments/generate-roadmap",
        "/api/v1/experiments/generate-roadmap-async",
        "/api/v1/code/analyze-repo",
        "/api/v1/code/analyze-repo-async",
        "/api/v1/code/diagnose",
        "/api/v1/results/analyze",
        "/api/v1/results/analyze-async",
    }
    if path in model_paths or (path.startswith("/api/v1/agents/") and path.endswith("/ask")):
        return RateRule("model", _positive_int("RATE_LIMIT_MODEL_REQUESTS", 20), 120)
    return None


def _client_key(request: Request) -> str:
    authorization = request.headers.get("authorization", "").strip()
    if authorization:
        digest = hashlib.sha256(authorization.encode("utf-8")).hexdigest()[:24]
        return f"token:{digest}"
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


class ApiRateLimitMiddleware(BaseHTTPMiddleware):
    """Bound abusive bursts without storing bearer tokens or request bodies."""

    def __init__(self, app):
        super().__init__(app)
        self._events: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        enabled = os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower() not in {
            "0", "false", "no", "off"
        }
        rule = _rule_for(request.url.path, request.method) if enabled else None
        if rule is None:
            return await call_next(request)

        now = time.monotonic()
        key = (rule.name, _client_key(request))
        async with self._lock:
            events = self._events.setdefault(key, deque())
            self._events.move_to_end(key)
            max_buckets = _positive_int("RATE_LIMIT_MAX_BUCKETS", 10_000)
            while len(self._events) > max_buckets:
                self._events.popitem(last=False)
            threshold = now - rule.window_seconds
            while events and events[0] <= threshold:
                events.popleft()
            if len(events) >= rule.requests:
                retry_after = max(1, int(rule.window_seconds - (now - events[0])))
                return JSONResponse(
                    status_code=429,
                    content={"detail": "请求过于频繁，请稍后重试"},
                    headers={"Retry-After": str(retry_after)},
                )
            events.append(now)
        return await call_next(request)

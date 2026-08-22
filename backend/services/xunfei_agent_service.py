import base64
import hashlib
import hmac
import json
import os
import time
from email.utils import formatdate
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv
from websocket import WebSocketTimeoutException, create_connection

from services.ai_metrics_service import build_usage_metadata
from services.external_service_reliability import (
    ExternalServiceError,
    load_external_service_policy,
    run_external_call,
)

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

AGENT_CONFIG_PREFIXES = {
    "problem-decomposition": "PROBLEM_DECOMPOSITION",
    "project-planning": "PROJECT_PLANNING",
    "result-interpretation": "RESULT_INTERPRETATION",
    "code-reproduction": "CODE_REPRODUCTION",
}


def _normalize_uid(user_id: str) -> str:
    if not user_id:
        return "anonymous_user"
    return user_id.replace("-", "")[:32]


def _signed_ws_url(api_key: str, api_secret: str, ws_url: str) -> str:
    parsed = urlsplit(ws_url)
    if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
        raise ValueError("Invalid Xunfei Agent WebSocket URL")

    host = parsed.netloc
    path = parsed.path or "/"
    date = formatdate(usegmt=True)
    signature_origin = f"host: {host}\ndate: {date}\nGET {path} HTTP/1.1"
    signature_sha = hmac.new(
        api_secret.encode("utf-8"),
        signature_origin.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    signature = base64.b64encode(signature_sha).decode("utf-8")
    authorization_origin = (
        f'api_key="{api_key}", '
        'algorithm="hmac-sha256", '
        'headers="host date request-line", '
        f'signature="{signature}"'
    )
    authorization = base64.b64encode(
        authorization_origin.encode("utf-8")
    ).decode("utf-8")

    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in {"authorization", "date", "host"}
    ]
    query_items.extend(
        [
            ("authorization", authorization),
            ("date", date),
            ("host", host),
        ]
    )
    return urlunsplit(
        (parsed.scheme, parsed.netloc, path, urlencode(query_items), "")
    )


def _paper_reading_ws_url() -> str:
    assistant_id = os.getenv("XF_AGENT_ASSISTANT_ID", "").strip()
    host = os.getenv(
        "XF_AGENT_WS_HOST", "spark-openapi.cn-huabei-1.xf-yun.com"
    ).strip()
    path_template = os.getenv(
        "XF_AGENT_WS_PATH", "/v1/assistants/{assistant_id}"
    ).strip()
    if not assistant_id:
        raise RuntimeError("Missing Xunfei config for category: paper-reading")
    path = path_template.replace("{assistant_id}", assistant_id)
    if path.startswith("ws://") or path.startswith("wss://"):
        return path
    return f"wss://{host}{path if path.startswith('/') else '/' + path}"


def get_xunfei_agent_config(agent_category: str) -> dict[str, str]:
    category = agent_category.strip().lower()
    if category == "paper-reading":
        config = {
            "app_id": os.getenv("XF_AGENT_APP_ID", "").strip(),
            "api_key": os.getenv("XF_AGENT_API_KEY", "").strip(),
            "api_secret": os.getenv("XF_AGENT_API_SECRET", "").strip(),
            "ws_url": _paper_reading_ws_url(),
        }
    else:
        prefix = AGENT_CONFIG_PREFIXES.get(category)
        if not prefix:
            raise RuntimeError(f"Unsupported Xunfei agent category: {category}")
        config = {
            "app_id": os.getenv(f"{prefix}_APP_ID", "").strip(),
            "api_key": os.getenv(f"{prefix}_API_KEY", "").strip(),
            "api_secret": os.getenv(f"{prefix}_API_SECRET", "").strip(),
            "ws_url": os.getenv(f"{prefix}_WS_URL", "").strip(),
        }

    if not all(config.values()):
        raise RuntimeError(f"Missing Xunfei config for category: {category}")
    return config


def call_xunfei_agent_with_config(
    user_id: str,
    user_message: str,
    app_id: str,
    api_key: str,
    api_secret: str,
    ws_url: str,
    max_tokens: int | None = None,
) -> str:
    result = call_xunfei_agent_with_config_metadata(
        user_id=user_id,
        user_message=user_message,
        app_id=app_id,
        api_key=api_key,
        api_secret=api_secret,
        ws_url=ws_url,
        max_tokens=max_tokens,
        _reliability_provider="xunfei-agent",
    )
    return str(result["text"])


def call_xunfei_agent_with_config_metadata(
    user_id: str,
    user_message: str,
    app_id: str,
    api_key: str,
    api_secret: str,
    ws_url: str,
    max_tokens: int | None = None,
    *,
    _reliability_provider: str = "xunfei-agent",
) -> dict[str, object]:
    if not user_message or not user_message.strip():
        raise ValueError("user_message cannot be empty")
    if not all((app_id, api_key, api_secret, ws_url)):
        raise RuntimeError("Incomplete Xunfei Agent configuration")

    policy = load_external_service_policy(
        "XF_AGENT",
        default_connect_timeout_seconds=10.0,
        default_read_timeout_seconds=120.0,
    )
    request_payload = {
        "header": {
            "app_id": app_id,
            "uid": _normalize_uid(user_id),
        },
        "parameter": {
            "chat": {
                "domain": os.getenv("XF_AGENT_DOMAIN", "generalv3"),
                "temperature": float(os.getenv("XF_AGENT_TEMPERATURE", "0.5")),
                "top_k": int(os.getenv("XF_AGENT_TOP_K", "4")),
                "max_tokens": max(
                    1,
                    min(
                        int(max_tokens or os.getenv("XF_AGENT_MAX_TOKENS", "2028")),
                        int(os.getenv("XF_AGENT_MAX_TOKENS", "2028")),
                    ),
                ),
            }
        },
        "payload": {
            "message": {
                "text": [{"role": "user", "content": user_message.strip()}]
            }
        },
    }

    def _call_once() -> tuple[str, object]:
        answer_parts: list[str] = []
        provider_usage: object = None
        websocket = None
        try:
            # Re-sign on every attempt so a retry never reuses a stale date.
            signed_url = _signed_ws_url(api_key, api_secret, ws_url)
            websocket = create_connection(
                signed_url,
                timeout=policy.connect_timeout_seconds,
            )
            deadline = time.monotonic() + policy.read_timeout_seconds
            websocket.settimeout(policy.read_timeout_seconds)
            websocket.send(json.dumps(request_payload, ensure_ascii=False))

            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise WebSocketTimeoutException("deadline exceeded")
                websocket.settimeout(max(0.001, remaining))
                raw_message = websocket.recv()
                data = json.loads(raw_message)
                header = data.get("header", {})
                code = header.get("code", 0)
                if code != 0:
                    raise ExternalServiceError(
                        "讯飞智能体调用失败，请检查后端 Agent 配置",
                        provider=_reliability_provider,
                        operation="websocket-chat",
                        kind="invalid_request",
                        retryable=False,
                        attempts=1,
                        provider_code=code,
                        provider_request_id=(
                            str(header.get("sid"))[:200]
                            if header.get("sid") is not None
                            else None
                        ),
                    )

                choices = data.get("payload", {}).get("choices", {})
                for item in choices.get("text", []):
                    answer_parts.append(str(item.get("content") or ""))
                usage = data.get("payload", {}).get("usage")
                if isinstance(usage, dict):
                    provider_usage = usage.get("text") or usage
                if header.get("status") == 2 or choices.get("status") == 2:
                    break
        finally:
            if websocket is not None:
                try:
                    websocket.close()
                except Exception:
                    pass

        reply = "".join(answer_parts).strip()
        if not reply:
            raise RuntimeError("Xunfei agent returned empty reply")
        return reply, provider_usage

    run = run_external_call(
        provider=_reliability_provider,
        operation="websocket-chat",
        display_name="讯飞智能体",
        policy=policy,
        call=_call_once,
        # WebSocket failure can occur after the request frame was accepted.
        # Agent generation has no idempotency key, so never replay it.
        allow_retry=False,
        default_retryable=False,
    )
    reply, provider_usage = run.value
    usage = build_usage_metadata(
        input_text=user_message,
        output_text=reply,
        provider_usage=provider_usage,
        price_prefix="XUNFEI_AGENT",
    )
    usage["external_run"] = run.summary
    return {
        "text": reply,
        "usage": usage,
        "runtime": run.summary,
    }


def call_xunfei_agent_by_category(
    user_id: str, user_message: str, agent_category: str
) -> str:
    config = get_xunfei_agent_config(agent_category)
    result = call_xunfei_agent_with_config_metadata(
        user_id=user_id,
        user_message=user_message,
        _reliability_provider=f"xunfei-agent:{agent_category.strip().lower()}",
        **config,
    )
    return str(result["text"])


def call_xunfei_agent_by_category_with_metadata(
    user_id: str,
    user_message: str,
    agent_category: str,
    max_tokens: int | None = None,
) -> dict[str, object]:
    config = get_xunfei_agent_config(agent_category)
    return call_xunfei_agent_with_config_metadata(
        user_id=user_id,
        user_message=user_message,
        max_tokens=max_tokens,
        _reliability_provider=f"xunfei-agent:{agent_category.strip().lower()}",
        **config,
    )


def call_paper_reading_agent(user_id: str, user_message: str) -> str:
    return call_xunfei_agent_by_category(
        user_id=user_id,
        user_message=user_message,
        agent_category="paper-reading",
    )

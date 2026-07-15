import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from email.utils import formatdate
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from dotenv import load_dotenv
from websocket import WebSocketTimeoutException, create_connection

load_dotenv()

XF_AGENT_APP_ID = os.getenv("XF_AGENT_APP_ID")
XF_AGENT_API_KEY = os.getenv("XF_AGENT_API_KEY")
XF_AGENT_API_SECRET = os.getenv("XF_AGENT_API_SECRET")
XF_AGENT_ASSISTANT_ID = os.getenv("XF_AGENT_ASSISTANT_ID")

XF_AGENT_WS_HOST = os.getenv(
    "XF_AGENT_WS_HOST",
    "spark-openapi.cn-huabei-1.xf-yun.com",
)
XF_AGENT_WS_PATH = os.getenv(
    "XF_AGENT_WS_PATH",
    "/v1/assistants/{assistant_id}",
)

PROBLEM_DECOMPOSITION_APP_ID = os.getenv("PROBLEM_DECOMPOSITION_APP_ID")
PROBLEM_DECOMPOSITION_API_KEY = os.getenv("PROBLEM_DECOMPOSITION_API_KEY")
PROBLEM_DECOMPOSITION_API_SECRET = os.getenv(
    "PROBLEM_DECOMPOSITION_API_SECRET"
)
PROBLEM_DECOMPOSITION_WS_URL = os.getenv("PROBLEM_DECOMPOSITION_WS_URL")

RESULT_INTERPRETATION_APP_ID = os.getenv("RESULT_INTERPRETATION_APP_ID")
RESULT_INTERPRETATION_API_KEY = os.getenv("RESULT_INTERPRETATION_API_KEY")
RESULT_INTERPRETATION_API_SECRET = os.getenv("RESULT_INTERPRETATION_API_SECRET")
RESULT_INTERPRETATION_WS_URL = os.getenv("RESULT_INTERPRETATION_WS_URL")

CODE_REPRODUCTION_APP_ID = os.getenv("CODE_REPRODUCTION_APP_ID")
CODE_REPRODUCTION_API_KEY = os.getenv("CODE_REPRODUCTION_API_KEY")
CODE_REPRODUCTION_API_SECRET = os.getenv("CODE_REPRODUCTION_API_SECRET")
CODE_REPRODUCTION_WS_URL = os.getenv("CODE_REPRODUCTION_WS_URL")

XF_AGENT_DOMAIN = os.getenv("XF_AGENT_DOMAIN", "generalv3")
XF_AGENT_TEMPERATURE = float(os.getenv("XF_AGENT_TEMPERATURE", "0.5"))
XF_AGENT_TOP_K = int(os.getenv("XF_AGENT_TOP_K", "4"))
XF_AGENT_MAX_TOKENS = int(os.getenv("XF_AGENT_MAX_TOKENS", "2028"))


@dataclass(frozen=True)
class XunfeiAgentConfig:
    app_id: str
    api_key: str
    api_secret: str
    ws_url: str


def _normalize_uid(user_id: str) -> str:
    if not user_id:
        return "anonymous_user"

    return user_id.replace("-", "")[:32]


def _build_paper_reading_ws_url() -> str:
    if not XF_AGENT_ASSISTANT_ID:
        return ""

    path = XF_AGENT_WS_PATH.replace("{assistant_id}", XF_AGENT_ASSISTANT_ID)
    return f"wss://{XF_AGENT_WS_HOST}{path}"


def _get_config_for_category(agent_category: str) -> XunfeiAgentConfig:
    configs = {
        "paper-reading": XunfeiAgentConfig(
            app_id=XF_AGENT_APP_ID or "",
            api_key=XF_AGENT_API_KEY or "",
            api_secret=XF_AGENT_API_SECRET or "",
            ws_url=_build_paper_reading_ws_url(),
        ),
        "problem-decomposition": XunfeiAgentConfig(
            app_id=PROBLEM_DECOMPOSITION_APP_ID or "",
            api_key=PROBLEM_DECOMPOSITION_API_KEY or "",
            api_secret=PROBLEM_DECOMPOSITION_API_SECRET or "",
            ws_url=PROBLEM_DECOMPOSITION_WS_URL or "",
        ),
        "result-interpretation": XunfeiAgentConfig(
            app_id=RESULT_INTERPRETATION_APP_ID or "",
            api_key=RESULT_INTERPRETATION_API_KEY or "",
            api_secret=RESULT_INTERPRETATION_API_SECRET or "",
            ws_url=RESULT_INTERPRETATION_WS_URL or "",
        ),
        "code-reproduction": XunfeiAgentConfig(
            app_id=CODE_REPRODUCTION_APP_ID or "",
            api_key=CODE_REPRODUCTION_API_KEY or "",
            api_secret=CODE_REPRODUCTION_API_SECRET or "",
            ws_url=CODE_REPRODUCTION_WS_URL or "",
        ),
    }

    config = configs.get(agent_category)
    if not config or not all(
        [config.app_id, config.api_key, config.api_secret, config.ws_url]
    ):
        raise RuntimeError(f"Missing Xunfei config for category: {agent_category}")

    return config


def _build_signed_ws_url(ws_url: str, api_key: str, api_secret: str) -> str:
    parsed = urlparse(ws_url)
    host = parsed.netloc
    path = parsed.path or "/"

    if not parsed.scheme or not host:
        raise RuntimeError("Invalid Xunfei WebSocket URL")

    date = formatdate(usegmt=True)
    signature_origin = (
        f"host: {host}\n"
        f"date: {date}\n"
        f"GET {path} HTTP/1.1"
    )

    signature_sha = hmac.new(
        api_secret.encode("utf-8"),
        signature_origin.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    signature = base64.b64encode(signature_sha).decode("utf-8")

    authorization_origin = (
        f'api_key="{api_key}", '
        f'algorithm="hmac-sha256", '
        f'headers="host date request-line", '
        f'signature="{signature}"'
    )
    authorization = base64.b64encode(
        authorization_origin.encode("utf-8")
    ).decode("utf-8")

    query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query_params.update(
        {
            "authorization": authorization,
            "date": date,
            "host": host,
        }
    )

    return urlunparse(
        (
            parsed.scheme,
            host,
            path,
            "",
            urlencode(query_params),
            "",
        )
    )


def call_xunfei_agent_with_config(
    user_id: str,
    user_message: str,
    app_id: str,
    api_key: str,
    api_secret: str,
    ws_url: str,
) -> str:
    if not user_message or not user_message.strip():
        raise ValueError("user_message cannot be empty")

    signed_ws_url = _build_signed_ws_url(
        ws_url=ws_url,
        api_key=api_key,
        api_secret=api_secret,
    )

    request_payload = {
        "header": {
            "app_id": app_id,
            "uid": _normalize_uid(user_id),
        },
        "parameter": {
            "chat": {
                "domain": XF_AGENT_DOMAIN,
                "temperature": XF_AGENT_TEMPERATURE,
                "top_k": XF_AGENT_TOP_K,
                "max_tokens": XF_AGENT_MAX_TOKENS,
            }
        },
        "payload": {
            "message": {
                "text": [
                    {
                        "role": "user",
                        "content": user_message,
                    }
                ]
            }
        },
    }

    answer_parts = []
    websocket = None

    try:
        # Keep connection establishment bounded, but allow a longer agent response.
        websocket = create_connection(signed_ws_url, timeout=30)
        websocket.settimeout(120)
        websocket.send(json.dumps(request_payload, ensure_ascii=False))

        while True:
            try:
                raw_message = websocket.recv()
            except WebSocketTimeoutException as exc:
                raise RuntimeError("Xunfei agent response timeout") from exc
            data = json.loads(raw_message)

            header = data.get("header", {})
            code = header.get("code", 0)

            if code != 0:
                raise RuntimeError(
                    f"Xunfei agent error: "
                    f"code={code}, "
                    f"message={header.get('message')}, "
                    f"sid={header.get('sid')}"
                )

            choices = data.get("payload", {}).get("choices", {})
            text_list = choices.get("text", [])

            for item in text_list:
                answer_parts.append(item.get("content", ""))

            header_status = header.get("status")
            choices_status = choices.get("status")

            if header_status == 2 or choices_status == 2:
                break
    finally:
        if websocket:
            websocket.close()

    reply = "".join(answer_parts).strip()
    if not reply:
        raise RuntimeError("Xunfei agent returned empty reply")

    return reply


def call_xunfei_agent(
    user_id: str,
    user_message: str,
    app_id: str,
    api_key: str,
    api_secret: str,
    ws_url: str,
) -> str:
    return call_xunfei_agent_with_config(
        user_id=user_id,
        user_message=user_message,
        app_id=app_id,
        api_key=api_key,
        api_secret=api_secret,
        ws_url=ws_url,
    )


def call_agent_by_category(
    user_id: str,
    user_message: str,
    agent_category: str,
) -> str:
    config = _get_config_for_category(agent_category)
    return call_xunfei_agent_with_config(
        user_id=user_id,
        user_message=user_message,
        app_id=config.app_id,
        api_key=config.api_key,
        api_secret=config.api_secret,
        ws_url=config.ws_url,
    )


def call_paper_reading_agent(user_id: str, user_message: str) -> str:
    return call_agent_by_category(
        user_id=user_id,
        user_message=user_message,
        agent_category="paper-reading",
    )

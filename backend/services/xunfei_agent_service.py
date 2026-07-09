import base64
import hashlib
import hmac
import json
import os
from email.utils import formatdate
from urllib.parse import urlencode

from dotenv import load_dotenv
from websocket import create_connection

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

XF_AGENT_DOMAIN = os.getenv("XF_AGENT_DOMAIN", "generalv3")
XF_AGENT_TEMPERATURE = float(os.getenv("XF_AGENT_TEMPERATURE", "0.5"))
XF_AGENT_TOP_K = int(os.getenv("XF_AGENT_TOP_K", "4"))
XF_AGENT_MAX_TOKENS = int(os.getenv("XF_AGENT_MAX_TOKENS", "2028"))


def _check_required_env():
    missing = []

    required = {
        "XF_AGENT_APP_ID": XF_AGENT_APP_ID,
        "XF_AGENT_API_KEY": XF_AGENT_API_KEY,
        "XF_AGENT_API_SECRET": XF_AGENT_API_SECRET,
        "XF_AGENT_ASSISTANT_ID": XF_AGENT_ASSISTANT_ID,
    }

    for key, value in required.items():
        if not value:
            missing.append(key)

    if missing:
        raise RuntimeError(
            "Missing Xunfei Agent env vars: " + ", ".join(missing)
        )


def _normalize_uid(user_id: str) -> str:
    """
    讯飞 uid 建议控制在 32 位以内。
    Supabase user_id 是 UUID，这里去掉横线后截取前 32 位。
    """
    if not user_id:
        return "anonymous_user"

    return user_id.replace("-", "")[:32]


def build_xf_agent_ws_url() -> str:
    """
    生成讯飞星辰 Agent WebSocket 鉴权 URL。
    """

    _check_required_env()

    path = XF_AGENT_WS_PATH.replace("{assistant_id}", XF_AGENT_ASSISTANT_ID)

    date = formatdate(usegmt=True)

    signature_origin = (
        f"host: {XF_AGENT_WS_HOST}\n"
        f"date: {date}\n"
        f"GET {path} HTTP/1.1"
    )

    signature_sha = hmac.new(
        XF_AGENT_API_SECRET.encode("utf-8"),
        signature_origin.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()

    signature = base64.b64encode(signature_sha).decode("utf-8")

    authorization_origin = (
        f'api_key="{XF_AGENT_API_KEY}", '
        f'algorithm="hmac-sha256", '
        f'headers="host date request-line", '
        f'signature="{signature}"'
    )

    authorization = base64.b64encode(
        authorization_origin.encode("utf-8")
    ).decode("utf-8")

    query = urlencode(
        {
            "authorization": authorization,
            "date": date,
            "host": XF_AGENT_WS_HOST,
        }
    )

    return f"wss://{XF_AGENT_WS_HOST}{path}?{query}"


def call_paper_reading_agent(user_id: str, user_message: str) -> str:
    """
    调用讯飞星辰论文精读 Agent。

    当前版本：
    - 后端接收讯飞的流式结果
    - 后端拼接成完整文本
    - 一次性返回给前端
    """

    if not user_message or not user_message.strip():
        raise ValueError("user_message cannot be empty")

    ws_url = build_xf_agent_ws_url()

    request_payload = {
        "header": {
            "app_id": XF_AGENT_APP_ID,
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
        websocket = create_connection(ws_url, timeout=60)

        websocket.send(
            json.dumps(
                request_payload,
                ensure_ascii=False,
            )
        )

        while True:
            raw_message = websocket.recv()
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
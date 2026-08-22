"""Server-side gateway for the published SciPilot Xunfei MaaS service.

The service card API key and every optional LoRA identifier stay in the backend.
The gateway accepts bounded conversation history so the dashboard behaves as a
real multi-turn chat instead of sending only the newest message.
"""

import os
from pathlib import Path
from typing import Mapping, Sequence

import httpx
from dotenv import load_dotenv
from openai import OpenAI

from services.ai_metrics_service import build_usage_metadata
from services.external_service_reliability import (
    external_service_runtime_snapshot,
    load_external_service_policy,
    run_external_call,
)


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DEFAULT_BASE_URL = "https://maas-api.cn-huabei-1.xf-yun.com/v2"
RELIABILITY_PROVIDER = "xunfei-maas"
_REQUIRED_SETTINGS = (
    "SCIPILOT_LLM_API_KEY",
    "SCIPILOT_LLM_MODEL_ID",
)


def is_finetuned_model_configured() -> bool:
    """Return whether the published MaaS service can be called."""

    return all(os.getenv(name, "").strip() for name in _REQUIRED_SETTINGS)


def is_lora_resource_configured() -> bool:
    """Return whether a concrete fine-tuning resource is explicitly selected."""

    resource_id = os.getenv("SCIPILOT_LLM_RESOURCE_ID", "").strip()
    return bool(resource_id and resource_id != "0")


def model_service_status() -> dict[str, object]:
    """Return a public, secret-free status payload for frontend health badges."""

    available = is_finetuned_model_configured()
    reliability = external_service_runtime_snapshot(RELIABILITY_PROVIDER)
    circuit_state = str((reliability.get("circuit") or {}).get("state") or "closed")
    return {
        "available": available,
        "fine_tuned": available and is_lora_resource_configured(),
        "model": os.getenv("SCIPILOT_LLM_MODEL_ID", "").strip() or None,
        "provider": RELIABILITY_PROVIDER,
        "transport": "http",
        "reason": (
            "模型服务连续失败，正在短暂冷却，请稍后重试"
            if available and circuit_state != "closed"
            else None
            if available
            else "模型服务尚未完成后端配置"
        ),
        "degraded": available and circuit_state != "closed",
        "reliability": reliability,
    }


def _require_setting(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing fine-tuned model setting: {name}")
    return value


def _response_content(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        ).strip()
    return ""


def _bounded_messages(
    messages: Sequence[Mapping[str, str]],
    *,
    max_messages: int = 20,
    max_characters: int = 48_000,
) -> list[dict[str, str]]:
    """Validate and trim history from the oldest conversational turn."""

    normalized: list[dict[str, str]] = []
    for message in messages:
        role = str(message.get("role") or "").strip()
        content = str(message.get("content") or "").strip()
        if role not in {"system", "user", "assistant"} or not content:
            continue
        normalized.append({"role": role, "content": content})

    if not normalized or normalized[-1]["role"] != "user":
        raise ValueError("messages must end with a non-empty user message")

    system = [item for item in normalized if item["role"] == "system"][:1]
    conversation = [item for item in normalized if item["role"] != "system"]
    selected: list[dict[str, str]] = []
    used = 0
    for item in reversed(conversation[-max_messages:]):
        length = len(item["content"])
        if selected and used + length > max_characters:
            break
        selected.append(item)
        used += length
    selected.reverse()
    return system + selected


def call_finetuned_model_with_metadata(
    *,
    system_prompt: str | None = None,
    user_message: str | None = None,
    messages: Sequence[Mapping[str, str]] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, object]:
    """Call the OpenAI-compatible MaaS endpoint.

    ``SCIPILOT_LLM_RESOURCE_ID`` is optional because some published service
    cards expose only a bound model service. When present it is sent as the
    documented ``lora_id`` header; when absent no identifier is guessed.
    """

    if messages is None:
        if not user_message or not user_message.strip():
            raise ValueError("user_message cannot be empty")
        messages = [
            *(
                [{"role": "system", "content": system_prompt.strip()}]
                if system_prompt and system_prompt.strip()
                else []
            ),
            {"role": "user", "content": user_message.strip()},
        ]
    request_messages = _bounded_messages(messages)

    api_key = _require_setting("SCIPILOT_LLM_API_KEY")
    model_id = _require_setting("SCIPILOT_LLM_MODEL_ID")
    resource_id = os.getenv("SCIPILOT_LLM_RESOURCE_ID", "").strip()
    base_url = os.getenv("SCIPILOT_LLM_BASE_URL", DEFAULT_BASE_URL).strip()
    base_url = (base_url or DEFAULT_BASE_URL).rstrip("/") + "/"
    policy = load_external_service_policy(
        "SCIPILOT_LLM",
        default_connect_timeout_seconds=10.0,
        default_read_timeout_seconds=120.0,
        read_timeout_aliases=("SCIPILOT_LLM_TIMEOUT_SECONDS",),
    )

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=httpx.Timeout(
            timeout=policy.read_timeout_seconds,
            connect=policy.connect_timeout_seconds,
        ),
        max_retries=0,
    )
    request: dict[str, object] = {
        "model": model_id,
        "messages": request_messages,
        "temperature": (
            temperature
            if temperature is not None
            else float(os.getenv("SCIPILOT_LLM_TEMPERATURE", "0.3"))
        ),
        "max_tokens": (
            max_tokens
            if max_tokens is not None
            else int(os.getenv("SCIPILOT_LLM_MAX_TOKENS", "2048"))
        ),
    }
    if resource_id:
        request["extra_headers"] = {"lora_id": resource_id}

    def _call_once() -> tuple[object, str]:
        response = client.chat.completions.create(**request)
        if not response.choices:
            raise RuntimeError("Fine-tuned model returned no choices")
        reply = _response_content(response.choices[0].message.content)
        if not reply:
            raise RuntimeError("Fine-tuned model returned empty reply")
        return response, reply

    run = run_external_call(
        provider=RELIABILITY_PROVIDER,
        operation="chat-completion",
        display_name="对话模型",
        policy=policy,
        call=_call_once,
        # A timeout can arrive after the provider accepted and billed a
        # generation. Without an idempotency key, replaying is quota-unsafe.
        allow_retry=False,
        default_retryable=False,
    )
    response, reply = run.value
    input_text = "\n".join(item["content"] for item in request_messages)
    usage = build_usage_metadata(
        input_text=input_text,
        output_text=reply,
        provider_usage=getattr(response, "usage", None),
        price_prefix="SCIPILOT_LLM",
    )
    usage["external_run"] = run.summary
    return {
        "text": reply,
        "usage": usage,
        "runtime": run.summary,
    }


def call_finetuned_model(
    *,
    system_prompt: str | None = None,
    user_message: str | None = None,
    messages: Sequence[Mapping[str, str]] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Compatibility wrapper returning only the generated text."""

    result = call_finetuned_model_with_metadata(
        system_prompt=system_prompt,
        user_message=user_message,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return str(result["text"])

"""Server-side client for the SciPilot fine-tuned Xunfei MaaS model."""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DEFAULT_BASE_URL = "https://maas-api.cn-huabei-1.xf-yun.com/v2"
_REQUIRED_SETTINGS = (
    "SCIPILOT_LLM_API_KEY",
    "SCIPILOT_LLM_MODEL_ID",
    "SCIPILOT_LLM_RESOURCE_ID",
)


def is_finetuned_model_configured() -> bool:
    """Return whether the backend has every secret needed for MaaS inference."""

    return all(os.getenv(name, "").strip() for name in _REQUIRED_SETTINGS)


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


def call_finetuned_model(
    *,
    system_prompt: str,
    user_message: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Call the OpenAI-compatible MaaS endpoint with the LoRA resource header.

    Credentials and the resource ID stay in the backend process. This function
    intentionally does not log request headers, URLs with credentials, or model
    payloads because they can contain sensitive project context.
    """

    if not user_message.strip():
        raise ValueError("user_message cannot be empty")

    api_key = _require_setting("SCIPILOT_LLM_API_KEY")
    model_id = _require_setting("SCIPILOT_LLM_MODEL_ID")
    resource_id = _require_setting("SCIPILOT_LLM_RESOURCE_ID")
    base_url = os.getenv("SCIPILOT_LLM_BASE_URL", DEFAULT_BASE_URL).strip()
    base_url = (base_url or DEFAULT_BASE_URL).rstrip("/") + "/"

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=120.0,
    )
    response = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=(
            temperature
            if temperature is not None
            else float(os.getenv("SCIPILOT_LLM_TEMPERATURE", "0.3"))
        ),
        max_tokens=(
            max_tokens
            if max_tokens is not None
            else int(os.getenv("SCIPILOT_LLM_MAX_TOKENS", "2048"))
        ),
        extra_headers={"lora_id": resource_id},
    )

    if not response.choices:
        raise RuntimeError("Fine-tuned model returned no choices")

    reply = _response_content(response.choices[0].message.content)
    if not reply:
        raise RuntimeError("Fine-tuned model returned empty reply")
    return reply

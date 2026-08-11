"""Privacy-safe usage normalization and optional cost estimation for AI calls."""

import math
import os
from typing import Any, Mapping


def estimate_tokens(text: str) -> int:
    """Return a conservative language-agnostic token estimate."""

    if not text:
        return 0
    return max(1, math.ceil(len(text.encode("utf-8")) / 4))


def _non_negative_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def normalize_provider_usage(usage: Any) -> dict[str, int] | None:
    """Normalize OpenAI- and Spark-shaped usage objects without retaining text."""

    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    elif not isinstance(usage, Mapping):
        usage = {
            key: getattr(usage, key, None)
            for key in (
                "prompt_tokens",
                "completion_tokens",
                "input_tokens",
                "output_tokens",
                "question_tokens",
                "total_tokens",
            )
        }
    if not isinstance(usage, Mapping):
        return None

    input_tokens = _non_negative_int(
        usage.get("input_tokens")
        or usage.get("prompt_tokens")
        or usage.get("question_tokens")
    )
    output_tokens = _non_negative_int(
        usage.get("output_tokens") or usage.get("completion_tokens")
    )
    if input_tokens is None and output_tokens is None:
        return None
    return {
        "input_tokens": input_tokens or 0,
        "output_tokens": output_tokens or 0,
    }


def _price(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def build_usage_metadata(
    *,
    input_text: str,
    output_text: str,
    provider_usage: Any = None,
    price_prefix: str,
) -> dict[str, Any]:
    """Build token metadata and estimate CNY cost only when prices are configured."""

    normalized = normalize_provider_usage(provider_usage)
    if normalized is None:
        input_tokens = estimate_tokens(input_text)
        output_tokens = estimate_tokens(output_text)
        usage_source = "estimated"
    else:
        input_tokens = normalized["input_tokens"]
        output_tokens = normalized["output_tokens"]
        usage_source = "provider"

    input_price = _price(f"{price_prefix}_INPUT_COST_CNY_PER_1M_TOKENS")
    output_price = _price(f"{price_prefix}_OUTPUT_COST_CNY_PER_1M_TOKENS")
    estimated_cost_cny = None
    if input_price is not None and output_price is not None:
        estimated_cost_cny = round(
            (input_tokens * input_price + output_tokens * output_price) / 1_000_000,
            6,
        )

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "usage_source": usage_source,
        "estimated_cost_cny": estimated_cost_cny,
        "token_usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "source": usage_source,
        },
    }

"""Pure normalization helpers shared by API route modules."""

import json
import re
from typing import Any


def parse_agent_json_object(raw_text: str) -> dict[str, Any] | None:
    """Extract a JSON object from plain text or a Markdown code fence."""

    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, count=1, flags=re.I)
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    json_text = cleaned[start : end + 1] if start >= 0 and end > start else cleaned

    try:
        data = json.loads(json_text)
    except (TypeError, ValueError, json.JSONDecodeError):
        data = None
    if isinstance(data, dict):
        return data

    # Paper reports place the optional graph after the required sections. If a
    # provider truncates that large suffix, preserve the complete report core.
    graph_match = re.search(r',\s*"graph"\s*:', json_text)
    if graph_match:
        try:
            report_data = json.loads(f"{json_text[:graph_match.start()]}\n}}")
        except (TypeError, ValueError, json.JSONDecodeError):
            report_data = None
        if isinstance(report_data, dict) and isinstance(
            report_data.get("sections"), list
        ):
            return report_data
    return None


def normalized_string_list(value: Any, *, limit: int = 10) -> list[str]:
    """Return a bounded, de-duplicated list of non-empty strings."""

    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text[:300])
        if len(items) >= limit:
            break
    return items

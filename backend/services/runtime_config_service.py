"""Secret-safe runtime configuration diagnostics for startup and tooling."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from services.external_service_reliability import (
    external_reliability_configuration_warnings,
)


PLACEHOLDER_MARKERS = (
    "your_",
    "your-",
    "placeholder",
    "example.com",
    "example.test",
)


@dataclass(frozen=True)
class RuntimeConfigReport:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def _value(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _enabled(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _configured(value: str) -> bool:
    lowered = value.lower()
    return bool(value) and not any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def _valid_url(value: str, schemes: set[str]) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in schemes and bool(parsed.netloc)


def _valid_secure_endpoint(
    value: str,
    scheme: str,
    *,
    origin_only: bool = False,
) -> bool:
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == scheme
        and bool(parsed.hostname)
        and not parsed.username
        and not parsed.password
        and (port is None or 1 <= port <= 65535)
        and (not origin_only or parsed.path in {"", "/"})
        and not parsed.fragment
        and (not origin_only or (not parsed.params and not parsed.query))
    )


def inspect_runtime_configuration() -> RuntimeConfigReport:
    errors: list[str] = []
    warnings: list[str] = []
    runtime = os.getenv("SCIPILOT_ENV", "production").strip().lower()
    local_demo = runtime == "local" and _enabled("LOCAL_DEMO_MODE")

    if local_demo:
        if not _configured(_value("LOCAL_DEMO_PASSWORD")):
            errors.append("LOCAL_DEMO_PASSWORD is required when local demo mode is enabled")
    else:
        supabase_url = _value("SUPABASE_URL")
        publishable = _value("SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY")
        secret = _value("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY")
        if not _configured(supabase_url) or not _valid_url(
            supabase_url, {"http", "https"}
        ):
            errors.append("SUPABASE_URL is missing, placeholder, or invalid")
        elif runtime == "production" and not _valid_secure_endpoint(
            supabase_url, "https", origin_only=True
        ):
            errors.append("SUPABASE_URL must be an origin-only HTTPS URL in production")
        if not _configured(publishable):
            errors.append("Supabase publishable/anon key is missing or still a placeholder")
        if not _configured(secret):
            errors.append("Supabase secret/service-role key is missing or still a placeholder")
        if publishable and secret and publishable == secret:
            errors.append("Supabase browser and backend keys must not be the same value")

    if runtime != "local" and _enabled("LOCAL_DEMO_MODE"):
        errors.append("LOCAL_DEMO_MODE must stay disabled outside local runtime")
    if runtime == "production" and _enabled("AUTH_AUTO_CONFIRM_EMAIL"):
        warnings.append("AUTH_AUTO_CONFIRM_EMAIL is enabled in production")

    origins = [item.strip() for item in os.getenv("CORS_ORIGINS", "").split(",")]
    if "*" in origins:
        errors.append("CORS_ORIGINS must not contain a wildcard")

    if runtime == "production":
        for name in ("SCIPILOT_LLM_BASE_URL", "XFYUN_KB_BASE_URL"):
            endpoint = _value(name)
            if endpoint and not _valid_secure_endpoint(endpoint, "https"):
                errors.append(f"{name} must be an absolute HTTPS URL in production")

        for name in (
            "PROBLEM_DECOMPOSITION_WS_URL",
            "PROJECT_PLANNING_WS_URL",
            "RESULT_INTERPRETATION_WS_URL",
            "CODE_REPRODUCTION_WS_URL",
        ):
            endpoint = _value(name)
            if endpoint and not _valid_secure_endpoint(endpoint, "wss"):
                errors.append(f"{name} must be an absolute WSS URL in production")

        paper_agent_path = _value("XF_AGENT_WS_PATH")
        if paper_agent_path.lower().startswith(
            ("ws://", "wss://")
        ) and not _valid_secure_endpoint(paper_agent_path, "wss"):
            errors.append(
                "XF_AGENT_WS_PATH must use WSS when configured as an absolute URL"
            )

    optional_groups = {
        "dashboard MaaS": (
            ("SCIPILOT_LLM_API_KEY",),
            ("SCIPILOT_LLM_MODEL_ID",),
        ),
        "Spark knowledge base": (
            ("XFYUN_KB_APP_ID",),
            ("XFYUN_KB_API_SECRET",),
            ("XFYUN_KB_REPO_ID",),
        ),
        "paper-reading Agent": (
            ("XF_AGENT_APP_ID",),
            ("XF_AGENT_API_KEY",),
            ("XF_AGENT_API_SECRET",),
            ("XF_AGENT_ASSISTANT_ID",),
        ),
    }
    for label, fields in optional_groups.items():
        states = [_configured(_value(*field)) for field in fields]
        if any(states) and not all(states):
            warnings.append(f"{label} configuration is incomplete")

    warnings.extend(external_reliability_configuration_warnings())

    return RuntimeConfigReport(tuple(errors), tuple(warnings))

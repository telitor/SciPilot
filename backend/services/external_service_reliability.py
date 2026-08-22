"""Bounded reliability controls for paid or remote AI dependencies.

The module intentionally knows nothing about prompts, documents, credentials, or
provider response bodies.  It records only bounded operational metadata so it is
safe to expose in health payloads and logs.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, TypeVar


logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class ExternalServicePolicy:
    """Safe, finite controls for one external service call."""

    connect_timeout_seconds: float
    read_timeout_seconds: float
    max_attempts: int = 2
    backoff_initial_seconds: float = 0.25
    backoff_max_seconds: float = 2.0
    circuit_failure_threshold: int = 3
    circuit_cooldown_seconds: float = 30.0


@dataclass(frozen=True)
class NormalizedExternalFailure:
    """Credential-safe classification of an arbitrary provider exception."""

    kind: str
    retryable: bool
    public_message: str
    http_status: int | None = None
    provider_code: int | str | None = None
    provider_request_id: str | None = None


@dataclass(frozen=True)
class ExternalCallResult:
    value: Any
    summary: dict[str, Any]


class ExternalServiceError(RuntimeError):
    """Normalized error that never includes raw upstream response content."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        operation: str,
        kind: str,
        retryable: bool,
        attempts: int,
        http_status: int | None = None,
        provider_code: int | str | None = None,
        provider_request_id: str | None = None,
        retry_after_seconds: float | None = None,
        run_summary: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.operation = operation
        self.kind = kind
        self.retryable = retryable
        self.attempts = attempts
        self.http_status = http_status
        self.provider_code = provider_code
        self.provider_request_id = provider_request_id
        self.retry_after_seconds = retry_after_seconds
        self.run_summary = dict(run_summary or {})


@dataclass
class _CircuitState:
    consecutive_failures: int = 0
    open_until: float = 0.0
    probe_in_flight: bool = False
    total_runs: int = 0
    successes: int = 0
    failures: int = 0
    retries: int = 0
    rejections: int = 0
    last_error_kind: str | None = None
    last_run: dict[str, Any] | None = field(default=None)


_STATE_LOCK = threading.Lock()
_CIRCUITS: dict[str, _CircuitState] = {}


def _first_env(names: tuple[str, ...]) -> tuple[str | None, str | None]:
    for name in names:
        raw = os.getenv(name)
        if raw is not None and raw.strip():
            return name, raw.strip()
    return None, None


def _bounded_number(
    names: tuple[str, ...],
    default: float,
    minimum: float,
    maximum: float,
    *,
    integer: bool = False,
) -> float | int:
    _, raw = _first_env(names)
    if raw is None:
        return int(default) if integer else float(default)
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return int(default) if integer else float(default)
    if not minimum <= parsed <= maximum or (integer and not parsed.is_integer()):
        return int(default) if integer else float(default)
    return int(parsed) if integer else parsed


def load_external_service_policy(
    env_prefix: str,
    *,
    default_connect_timeout_seconds: float = 10.0,
    default_read_timeout_seconds: float = 120.0,
    connect_timeout_aliases: tuple[str, ...] = (),
    read_timeout_aliases: tuple[str, ...] = (),
) -> ExternalServicePolicy:
    """Load bounded provider overrides with shared fallbacks.

    Invalid or unsafe values fail closed to the documented defaults.  Startup
    diagnostics separately report the offending variable names.
    """

    connect_timeout = _bounded_number(
        (
            f"{env_prefix}_CONNECT_TIMEOUT_SECONDS",
            *connect_timeout_aliases,
            "SCIPILOT_EXTERNAL_CONNECT_TIMEOUT_SECONDS",
        ),
        default_connect_timeout_seconds,
        0.1,
        60.0,
    )
    read_timeout = _bounded_number(
        (
            f"{env_prefix}_READ_TIMEOUT_SECONDS",
            *read_timeout_aliases,
            "SCIPILOT_EXTERNAL_READ_TIMEOUT_SECONDS",
        ),
        default_read_timeout_seconds,
        1.0,
        600.0,
    )
    attempts = _bounded_number(
        (f"{env_prefix}_MAX_ATTEMPTS", "SCIPILOT_EXTERNAL_MAX_ATTEMPTS"),
        2,
        1,
        3,
        integer=True,
    )
    initial_backoff = _bounded_number(
        (
            f"{env_prefix}_BACKOFF_INITIAL_SECONDS",
            "SCIPILOT_EXTERNAL_BACKOFF_INITIAL_SECONDS",
        ),
        0.25,
        0.0,
        10.0,
    )
    maximum_backoff = _bounded_number(
        (
            f"{env_prefix}_BACKOFF_MAX_SECONDS",
            "SCIPILOT_EXTERNAL_BACKOFF_MAX_SECONDS",
        ),
        2.0,
        0.0,
        30.0,
    )
    failure_threshold = _bounded_number(
        (
            f"{env_prefix}_CIRCUIT_FAILURE_THRESHOLD",
            "SCIPILOT_EXTERNAL_CIRCUIT_FAILURE_THRESHOLD",
        ),
        3,
        1,
        20,
        integer=True,
    )
    cooldown = _bounded_number(
        (
            f"{env_prefix}_CIRCUIT_COOLDOWN_SECONDS",
            "SCIPILOT_EXTERNAL_CIRCUIT_COOLDOWN_SECONDS",
        ),
        30.0,
        1.0,
        600.0,
    )
    return ExternalServicePolicy(
        connect_timeout_seconds=float(connect_timeout),
        read_timeout_seconds=float(read_timeout),
        max_attempts=int(attempts),
        backoff_initial_seconds=float(initial_backoff),
        backoff_max_seconds=max(float(initial_backoff), float(maximum_backoff)),
        circuit_failure_threshold=int(failure_threshold),
        circuit_cooldown_seconds=float(cooldown),
    )


def _status_code(exc: Exception) -> int | None:
    direct = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    nested = getattr(response, "status_code", None)
    for candidate in (direct, nested, getattr(exc, "http_status", None)):
        try:
            if candidate is not None:
                return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _public_message(display_name: str, kind: str) -> str:
    messages = {
        "timeout": f"{display_name}响应超时，请稍后重试",
        "connection": f"{display_name}连接暂时不可用，请稍后重试",
        "rate_limited": f"{display_name}当前请求较多，请稍后重试",
        "circuit_open": f"{display_name}连续失败，正在短暂冷却，请稍后重试",
        "authentication": f"{display_name}认证失败，请检查后端服务配置",
        "invalid_request": f"{display_name}拒绝了请求，请检查后端服务配置",
        "invalid_response": f"{display_name}返回了无效响应，请稍后重试",
        "unavailable": f"{display_name}暂时不可用，请稍后重试",
    }
    return messages.get(kind, messages["unavailable"])


def normalize_external_exception(
    exc: Exception,
    *,
    display_name: str,
    default_retryable: bool = False,
) -> NormalizedExternalFailure:
    """Classify provider/SDK errors without copying their raw message."""

    if isinstance(exc, ExternalServiceError):
        return NormalizedExternalFailure(
            kind=exc.kind,
            retryable=exc.retryable,
            public_message=str(exc),
            http_status=exc.http_status,
            provider_code=exc.provider_code,
            provider_request_id=exc.provider_request_id,
        )

    explicit_kind = getattr(exc, "kind", None)
    explicit_retryable = getattr(exc, "retryable", None)
    if isinstance(explicit_kind, str) and isinstance(explicit_retryable, bool):
        return NormalizedExternalFailure(
            kind=explicit_kind,
            retryable=explicit_retryable,
            public_message=str(exc),
            http_status=_status_code(exc),
            provider_code=(
                getattr(exc, "code", None)
                if isinstance(getattr(exc, "code", None), (int, str))
                else None
            ),
            provider_request_id=(
                str(getattr(exc, "sid"))[:200]
                if getattr(exc, "sid", None) is not None
                else None
            ),
        )

    status = _status_code(exc)
    class_name = type(exc).__name__.lower()
    if isinstance(exc, TimeoutError) or "timeout" in class_name:
        kind, retryable = "timeout", True
    elif status == 429:
        kind, retryable = "rate_limited", True
    elif status in {408, 425} or (status is not None and status >= 500):
        kind, retryable = "unavailable", True
    elif status in {401, 403}:
        kind, retryable = "authentication", False
    elif status is not None and 400 <= status < 500:
        kind, retryable = "invalid_request", False
    elif isinstance(exc, (ConnectionError, OSError)) or "connection" in class_name:
        kind, retryable = "connection", True
    elif isinstance(exc, (TypeError, ValueError)):
        kind, retryable = "invalid_response", False
    else:
        kind, retryable = "unavailable", default_retryable

    code = getattr(exc, "code", None)
    request_id = getattr(exc, "sid", None) or getattr(exc, "request_id", None)
    return NormalizedExternalFailure(
        kind=kind,
        retryable=retryable,
        public_message=_public_message(display_name, kind),
        http_status=status,
        provider_code=code if isinstance(code, (int, str)) else None,
        provider_request_id=(str(request_id)[:200] if request_id is not None else None),
    )


def _circuit_view(state: _CircuitState, now: float) -> dict[str, Any]:
    remaining = max(0.0, state.open_until - now)
    if remaining > 0:
        circuit_status = "open"
    elif state.probe_in_flight:
        circuit_status = "half_open"
    else:
        circuit_status = "closed"
    return {
        "state": circuit_status,
        "consecutive_failures": state.consecutive_failures,
        "cooldown_remaining_seconds": round(remaining, 3),
    }


def _emit_summary(summary: Mapping[str, Any]) -> None:
    logger.info(
        "external_service_run provider=%s operation=%s status=%s attempts=%s "
        "retries=%s latency_ms=%s error_kind=%s circuit=%s",
        summary.get("provider"),
        summary.get("operation"),
        summary.get("status"),
        summary.get("attempts"),
        summary.get("retries"),
        summary.get("latency_ms"),
        summary.get("error_kind"),
        (summary.get("circuit") or {}).get("state"),
    )


def run_external_call(
    *,
    provider: str,
    operation: str,
    display_name: str,
    policy: ExternalServicePolicy,
    call: Callable[[], T],
    allow_retry: bool = True,
    default_retryable: bool = False,
    classify: Callable[[Exception], NormalizedExternalFailure] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
) -> ExternalCallResult:
    """Execute one bounded call with retry, backoff, and an in-process circuit."""

    sleep = sleep_fn or time.sleep
    monotonic = clock or time.monotonic
    started = monotonic()
    with _STATE_LOCK:
        state = _CIRCUITS.setdefault(provider, _CircuitState())
        now = monotonic()
        if state.open_until > now or state.probe_in_flight:
            state.rejections += 1
            remaining = max(0.0, state.open_until - now)
            summary = {
                "provider": provider,
                "operation": operation,
                "status": "rejected",
                "attempts": 0,
                "retries": 0,
                "latency_ms": 0,
                "degraded": True,
                "degradation_hint": "circuit-open-cooldown",
                "error_kind": "circuit_open",
                "circuit": _circuit_view(state, now),
            }
            state.last_run = summary
            _emit_summary(summary)
            raise ExternalServiceError(
                _public_message(display_name, "circuit_open"),
                provider=provider,
                operation=operation,
                kind="circuit_open",
                retryable=True,
                attempts=0,
                retry_after_seconds=remaining,
                run_summary=summary,
            ) from None
        if state.open_until:
            state.open_until = 0.0
            state.probe_in_flight = True
        state.total_runs += 1

    attempts = 0
    failure: NormalizedExternalFailure | None = None
    max_attempts = policy.max_attempts if allow_retry else 1
    while attempts < max_attempts:
        attempts += 1
        try:
            value = call()
        except Exception as exc:
            failure = (
                classify(exc)
                if classify is not None
                else normalize_external_exception(
                    exc,
                    display_name=display_name,
                    default_retryable=default_retryable,
                )
            )
            if not failure.retryable or attempts >= max_attempts:
                break
            delay = min(
                policy.backoff_max_seconds,
                policy.backoff_initial_seconds * (2 ** (attempts - 1)),
            )
            if delay > 0:
                sleep(delay)
        else:
            finished = monotonic()
            with _STATE_LOCK:
                state = _CIRCUITS.setdefault(provider, _CircuitState())
                state.successes += 1
                state.retries += max(0, attempts - 1)
                state.consecutive_failures = 0
                state.open_until = 0.0
                state.probe_in_flight = False
                summary = {
                    "provider": provider,
                    "operation": operation,
                    "status": "succeeded",
                    "attempts": attempts,
                    "retries": max(0, attempts - 1),
                    "latency_ms": max(0, round((finished - started) * 1000)),
                    "degraded": attempts > 1,
                    "degradation_hint": (
                        "recovered-after-retry" if attempts > 1 else None
                    ),
                    "error_kind": None,
                    "circuit": _circuit_view(state, finished),
                }
                state.last_error_kind = None
                state.last_run = summary
            _emit_summary(summary)
            return ExternalCallResult(value=value, summary=summary)

    assert failure is not None
    finished = monotonic()
    with _STATE_LOCK:
        state = _CIRCUITS.setdefault(provider, _CircuitState())
        state.failures += 1
        state.retries += max(0, attempts - 1)
        state.consecutive_failures += 1
        state.probe_in_flight = False
        state.last_error_kind = failure.kind
        if state.consecutive_failures >= policy.circuit_failure_threshold:
            state.open_until = finished + policy.circuit_cooldown_seconds
        summary = {
            "provider": provider,
            "operation": operation,
            "status": "failed",
            "attempts": attempts,
            "retries": max(0, attempts - 1),
            "latency_ms": max(0, round((finished - started) * 1000)),
            "degraded": True,
            "degradation_hint": (
                "circuit-open-cooldown"
                if state.open_until > finished
                else "provider-unavailable"
            ),
            "error_kind": failure.kind,
            "circuit": _circuit_view(state, finished),
        }
        state.last_run = summary
    _emit_summary(summary)
    raise ExternalServiceError(
        failure.public_message,
        provider=provider,
        operation=operation,
        kind=failure.kind,
        retryable=failure.retryable,
        attempts=attempts,
        http_status=failure.http_status,
        provider_code=failure.provider_code,
        provider_request_id=failure.provider_request_id,
        retry_after_seconds=max(0.0, state.open_until - finished) or None,
        run_summary=summary,
    ) from None


def external_service_runtime_snapshot(provider: str) -> dict[str, Any]:
    """Return a bounded, secret-free process-local service summary."""

    now = time.monotonic()
    with _STATE_LOCK:
        state = _CIRCUITS.get(provider, _CircuitState())
        return {
            "provider": provider,
            "total_runs": state.total_runs,
            "successes": state.successes,
            "failures": state.failures,
            "retries": state.retries,
            "circuit_rejections": state.rejections,
            "last_error_kind": state.last_error_kind,
            "circuit": _circuit_view(state, now),
            "last_run": dict(state.last_run) if state.last_run else None,
        }


def summarize_external_runs(runs: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate per-operation summaries without retaining request content."""

    clean = [dict(item) for item in runs[-20:] if isinstance(item, Mapping)]
    failed = [item for item in clean if item.get("status") != "succeeded"]
    return {
        "status": "failed" if failed else "degraded" if any(
            item.get("degraded") for item in clean
        ) else "succeeded",
        "operation_count": len(clean),
        "attempts": sum(max(0, int(item.get("attempts") or 0)) for item in clean),
        "retries": sum(max(0, int(item.get("retries") or 0)) for item in clean),
        "latency_ms": sum(max(0, int(item.get("latency_ms") or 0)) for item in clean),
        "degraded": bool(failed) or any(item.get("degraded") for item in clean),
        "degradation_hint": (
            str(failed[-1].get("degradation_hint") or "provider-unavailable")
            if failed
            else "recovered-after-retry"
            if any(item.get("degraded") for item in clean)
            else None
        ),
        "operations": clean,
    }


def reset_external_service_runtime_state() -> None:
    """Clear only process-local counters; intended for isolated unit tests."""

    with _STATE_LOCK:
        _CIRCUITS.clear()


_CONFIG_RULES: tuple[tuple[str, float, float, bool], ...] = (
    ("SCIPILOT_EXTERNAL_CONNECT_TIMEOUT_SECONDS", 0.1, 60.0, False),
    ("SCIPILOT_EXTERNAL_READ_TIMEOUT_SECONDS", 1.0, 600.0, False),
    ("SCIPILOT_EXTERNAL_MAX_ATTEMPTS", 1, 3, True),
    ("SCIPILOT_EXTERNAL_BACKOFF_INITIAL_SECONDS", 0.0, 10.0, False),
    ("SCIPILOT_EXTERNAL_BACKOFF_MAX_SECONDS", 0.0, 30.0, False),
    ("SCIPILOT_EXTERNAL_CIRCUIT_FAILURE_THRESHOLD", 1, 20, True),
    ("SCIPILOT_EXTERNAL_CIRCUIT_COOLDOWN_SECONDS", 1.0, 600.0, False),
    ("SCIPILOT_LLM_CONNECT_TIMEOUT_SECONDS", 0.1, 60.0, False),
    ("SCIPILOT_LLM_READ_TIMEOUT_SECONDS", 1.0, 600.0, False),
    ("SCIPILOT_LLM_TIMEOUT_SECONDS", 1.0, 600.0, False),
    ("XF_AGENT_CONNECT_TIMEOUT_SECONDS", 0.1, 60.0, False),
    ("XF_AGENT_READ_TIMEOUT_SECONDS", 1.0, 600.0, False),
    ("XFYUN_KB_CONNECT_TIMEOUT_SECONDS", 0.1, 60.0, False),
    ("XFYUN_KB_READ_TIMEOUT_SECONDS", 1.0, 600.0, False),
    ("XFYUN_KB_CONNECT_TIMEOUT", 0.1, 60.0, False),
    ("XFYUN_KB_READ_TIMEOUT", 1.0, 600.0, False),
)


def external_reliability_configuration_warnings() -> tuple[str, ...]:
    """Return variable names whose values will be replaced by safe defaults."""

    warnings: list[str] = []
    rules = list(_CONFIG_RULES)
    provider_prefixes = ("SCIPILOT_LLM", "XF_AGENT", "XFYUN_KB")
    provider_suffixes = (
        ("MAX_ATTEMPTS", 1, 3, True),
        ("BACKOFF_INITIAL_SECONDS", 0.0, 10.0, False),
        ("BACKOFF_MAX_SECONDS", 0.0, 30.0, False),
        ("CIRCUIT_FAILURE_THRESHOLD", 1, 20, True),
        ("CIRCUIT_COOLDOWN_SECONDS", 1.0, 600.0, False),
    )
    for prefix in provider_prefixes:
        for suffix, minimum, maximum, integer in provider_suffixes:
            rules.append((f"{prefix}_{suffix}", minimum, maximum, integer))

    for name, minimum, maximum, integer in rules:
        raw = os.getenv(name)
        if raw is None or not raw.strip():
            continue
        try:
            parsed = float(raw.strip())
            valid = minimum <= parsed <= maximum and (
                not integer or parsed.is_integer()
            )
        except (TypeError, ValueError):
            valid = False
        if not valid:
            warnings.append(
                f"{name} is invalid or outside its safe range; using the safe default"
            )
    return tuple(warnings)

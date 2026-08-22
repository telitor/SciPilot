# External AI service reliability

SciPilot applies one reliability boundary to the three paid/remote AI paths in
`backend/services`: Xunfei Star Agent (WebSocket), Xunfei MaaS (OpenAI-compatible
HTTP), and Spark ChatDoc (HTTP/SSE). The boundary never records prompts,
documents, credentials, signed URLs, provider bodies, or exception strings.

## Default policy

| Control | Default | Bound | Behaviour |
| --- | ---: | ---: | --- |
| Connect timeout | 10 s | 0.1–60 s | Stops stalled connection setup. |
| Read timeout | 120 s | 1–600 s | Bounds one provider attempt. Agent uses a total response deadline, not an unlimited timeout per frame. |
| Maximum attempts | 2 | 1–3 | Includes the first attempt and applies only to explicitly retry-safe read/status/search operations. |
| Initial/max backoff | 0.25 / 2 s | 0–10 / 0–30 s | Deterministic exponential backoff. |
| Circuit threshold | 3 failed logical calls | 1–20 | Opens after consecutive final failures. |
| Cooldown | 30 s | 1–600 s | Rejects calls locally, then permits one half-open probe. |

The shared variables are documented in `backend/.env.example` and start with
`SCIPILOT_EXTERNAL_`. A service can override retry/backoff/circuit controls with
the same suffix under `SCIPILOT_LLM_`, `XF_AGENT_`, or `XFYUN_KB_`. For example,
`XFYUN_KB_MAX_ATTEMPTS=3` overrides the shared attempt count for ChatDoc only.
Unsafe or malformed values fall back to defaults and appear as a secret-free
startup warning from `runtime_config_service`.

Existing timeout names remain compatible:

- MaaS: `SCIPILOT_LLM_TIMEOUT_SECONDS`
- Agent: `XF_AGENT_CONNECT_TIMEOUT_SECONDS`, `XF_AGENT_READ_TIMEOUT_SECONDS`
- ChatDoc: `XFYUN_KB_CONNECT_TIMEOUT`, `XFYUN_KB_READ_TIMEOUT`

## Retry and quota safety

- MaaS and Agent generation calls disable hidden SDK retries and are executed
  once. A timeout may arrive after the provider accepted and billed a request;
  without an idempotency key SciPilot must not replay it automatically.
- ChatDoc retries only read/status/search operations. File upload, file delete,
  and generated SSE answers are also single-attempt because ChatDoc does not
  expose an idempotency key and the first request may already have consumed
  quota.
- HTTP 408/425/429/5xx, connection failures, and timeouts are transient.
  Authentication, request validation, and provider-declared request errors are
  permanent for that logical call.

## Error and degradation contract

Provider exceptions are converted to `ExternalServiceError` (or the compatible
`XunfeiKnowledgeBaseError`) with only: provider, operation, error kind, retry
status, attempts, safe HTTP/provider codes, cooldown, and a public message. Raw
provider text never crosses the service boundary.

The API keeps its existing success and failure semantics. On a normalized
failure it returns the existing upstream HTTP status with a safe, actionable
message; an open circuit also supplies `Retry-After`. Dashboard chat continues
without ChatDoc when retrieval is unavailable and returns an explicit
`degradation_hint` instead of silently claiming knowledge-base grounding.

## Runtime summaries

Every logical external call emits a structured log and a bounded summary:

```json
{
  "provider": "xunfei-chatdoc",
  "operation": "retrieval",
  "status": "succeeded",
  "attempts": 2,
  "retries": 1,
  "latency_ms": 438,
  "degraded": true,
  "degradation_hint": "recovered-after-retry",
  "error_kind": null,
  "circuit": {
    "state": "closed",
    "consecutive_failures": 0,
    "cooldown_remaining_seconds": 0
  }
}
```

MaaS and Agent metadata attach the summary to both `runtime` and
`usage.external_run`, reusing the existing token/cost metrics path. ChatDoc
aggregates its bounded per-operation summaries into knowledge status/search/
answer payloads. Dashboard model status includes the process-local circuit
snapshot. These summaries contain no input or output content.

The circuit is intentionally process-local. A multi-worker deployment should
also enforce upstream protection at the gateway and aggregate the structured
logs centrally; no request depends on shared circuit state for correctness.

## Offline verification

The reliability tests use fake callables, sessions, WebSockets, and clocks. They
cover retry/backoff, non-retryable errors, cooldown/half-open recovery, timeout
propagation, secret redaction, and runtime summaries without making network
requests or consuming provider quota.

```powershell
backend\.venv\Scripts\python.exe -m unittest backend.tests.test_external_service_reliability backend.tests.test_finetuned_model_service backend.tests.test_xunfei_agent_reliability backend.tests.test_xunfei_knowledge_base_service
```

"""Run the bounded real-provider suite against a deployed SciPilot API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    default_port = 443 if scheme == "https" else 80 if scheme == "http" else None
    return scheme, (parsed.hostname or "").lower(), parsed.port or default_port


class _SameOriginHttpsRedirectHandler(HTTPRedirectHandler):
    """Follow redirects only when an admin bearer remains on one HTTPS origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        parsed_target = urlparse(target)
        if (
            parsed_target.scheme.lower() != "https"
            or parsed_target.username is not None
            or parsed_target.password is not None
            or _origin(target) != _origin(req.full_url)
        ):
            raise HTTPError(
                req.full_url,
                code,
                "unsafe deployed-smoke redirect blocked",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, target)


_HTTPS_SAME_ORIGIN_OPENER = build_opener(_SameOriginHttpsRedirectHandler())


def _request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    token: str | None = None,
    timeout: int = 60,
) -> object:
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        data=body,
        headers=headers,
        method=method,
    )
    with _HTTPS_SAME_ORIGIN_OPENER.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("SCIPILOT_SMOKE_BASE_URL", ""))
    parser.add_argument("--confirm-external-calls", action="store_true")
    parser.add_argument("--allow-http", action="store_true")
    args = parser.parse_args()
    if not args.confirm_external_calls:
        parser.error("--confirm-external-calls is required because this consumes provider quota")
    parsed = urlparse(args.base_url.strip())
    if parsed.scheme not in ({"http", "https"} if args.allow_http else {"https"}) or not parsed.netloc:
        parser.error("--base-url must be an absolute HTTPS URL")
    email = os.getenv("SCIPILOT_SMOKE_EMAIL", "").strip()
    password = os.getenv("SCIPILOT_SMOKE_PASSWORD", "")
    if not email or not password:
        parser.error("SCIPILOT_SMOKE_EMAIL and SCIPILOT_SMOKE_PASSWORD are required")

    try:
        health = _request_json(args.base_url, "/api/v1/health")
        if not isinstance(health, dict) or health.get("status") != "ok":
            raise RuntimeError("deployment health endpoint is not ready")
        login = _request_json(
            args.base_url,
            "/api/v1/auth/login",
            method="POST",
            payload={"email": email, "password": password},
        )
        token = str(login.get("token") or "") if isinstance(login, dict) else ""
        if not token:
            raise RuntimeError("smoke account login did not return an access token")
        suites = _request_json(
            args.base_url,
            "/api/v1/admin/evaluations/suites",
            token=token,
        )
        suite = next(
            (
                item
                for item in suites
                if isinstance(item, dict) and item.get("module") == "real-model-smoke"
            ),
            None,
        ) if isinstance(suites, list) else None
        if not suite:
            raise RuntimeError("no active real-model-smoke suite is configured")
        result = _request_json(
            args.base_url,
            "/api/v1/admin/evaluations/runs",
            method="POST",
            payload={
                "suite_slug": suite["slug"],
                "mode": "real-model",
                "confirm_external_calls": True,
            },
            token=token,
            timeout=900,
        )
    except HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", errors="replace")
        print(f"Deployed smoke failed with HTTP {exc.code}: {detail}", file=sys.stderr)
        return 1
    except (URLError, OSError, RuntimeError, ValueError) as exc:
        print(f"Deployed smoke failed: {exc}", file=sys.stderr)
        return 1

    if not isinstance(result, dict) or result.get("status") != "completed":
        print("Deployed smoke did not complete successfully.", file=sys.stderr)
        return 1
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    print(
        "Deployed real-provider smoke completed: "
        f"{result.get('passed_count', 0)}/{result.get('case_count', 0)} passed, "
        f"p95={metrics.get('p95_latency_ms', 0)}ms, "
        f"known_cost_cny={metrics.get('estimated_cost_cny', 0)}."
    )
    return 0 if result.get("failed_count") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

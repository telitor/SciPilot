#!/usr/bin/env python3
"""Secret-safe release, rollback, and smoke verification for SciPilot.

The script intentionally uses only the Python standard library. It never prints
environment values and passes arguments to Docker without invoking a shell.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_DIR = ROOT / "deploy"
COMPOSE_FILE = DEPLOY_DIR / "compose.yaml"
DEFAULT_ENV_FILE = DEPLOY_DIR / ".env"
STATE_FILE = DEPLOY_DIR / ".state" / "releases.json"
BACKEND_DIR = ROOT / "backend"

ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RELEASE_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MUTABLE_TAGS = {"dev", "latest", "main", "master", "stable"}
TRUTHY = {"1", "true", "yes", "on"}
FALSY = {"0", "false", "no", "off"}


class DeploymentError(RuntimeError):
    """A deployment validation or orchestration failure."""


def _strip_inline_comment(value: str) -> str:
    for index, character in enumerate(value):
        if character == "#" and index > 0 and value[index - 1].isspace():
            return value[:index].rstrip()
    return value


def load_env_file(path: Path) -> dict[str, str]:
    """Parse the conservative KEY=VALUE subset shared by Docker Compose."""

    if not path.is_file():
        raise DeploymentError(
            f"Environment file is missing: {path}. Copy deploy/.env.example first."
        )

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise DeploymentError(f"Invalid environment entry at {path}:{line_number}")
        name, raw_value = line.split("=", 1)
        name = name.strip()
        if not ENV_NAME.fullmatch(name):
            raise DeploymentError(
                f"Invalid environment variable name at {path}:{line_number}"
            )
        if name in values:
            raise DeploymentError(
                f"Duplicate environment variable {name} at {path}:{line_number}"
            )
        raw_value = raw_value.strip()
        if raw_value.startswith(("'", '"')):
            quote = raw_value[0]
            if len(raw_value) < 2 or not raw_value.endswith(quote):
                raise DeploymentError(
                    f"Unclosed quoted value for {name} at {path}:{line_number}"
                )
            value = raw_value[1:-1]
        else:
            value = _strip_inline_comment(raw_value)
        values[name] = value
    return values


def _bool_value(values: Mapping[str, str], name: str, default: str) -> bool | None:
    normalized = values.get(name, default).strip().lower()
    if normalized in TRUTHY:
        return True
    if normalized in FALSY:
        return False
    return None


@contextmanager
def _isolated_environment(values: Mapping[str, str]) -> Iterator[None]:
    previous = dict(os.environ)
    os.environ.clear()
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


def _runtime_configuration_issues(
    values: Mapping[str, str],
) -> tuple[list[str], list[str]]:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    from services.runtime_config_service import inspect_runtime_configuration

    with _isolated_environment(values):
        report = inspect_runtime_configuration()
    return list(report.errors), list(report.warnings)


def _valid_https_origin(value: str) -> bool:
    parsed = urlparse(value)
    try:
        parsed_port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and not parsed.username
        and not parsed.password
        and (parsed_port is None or 1 <= parsed_port <= 65535)
        and parsed.path in {"", "/"}
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )


def _valid_secure_endpoint(value: str, scheme: str) -> bool:
    parsed = urlparse(value)
    try:
        parsed_port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == scheme
        and bool(parsed.hostname)
        and not parsed.username
        and not parsed.password
        and (parsed_port is None or 1 <= parsed_port <= 65535)
        and not parsed.fragment
    )


def _origin(value: str) -> str:
    parsed = urlparse(value)
    host = parsed.hostname or ""
    default_port = 443 if parsed.scheme == "https" else 80
    port = parsed.port or default_port
    suffix = "" if port == default_port else f":{port}"
    return f"{parsed.scheme}://{host}{suffix}"


def _documentation_hostname(value: str) -> bool:
    hostname = (urlparse(value).hostname or "").lower()
    reserved = ("example.com", "example.net", "example.org")
    return hostname in reserved or hostname.endswith(
        (
            ".example.com",
            ".example.net",
            ".example.org",
            ".example",
            ".invalid",
            ".localhost",
            ".test",
        )
    )


def validate_release_tag(tag: str) -> list[str]:
    normalized = tag.strip()
    issues: list[str] = []
    if not RELEASE_TAG.fullmatch(normalized):
        issues.append(
            "SCIPILOT_IMAGE_TAG must contain only letters, digits, dot, underscore, "
            "or dash (maximum 128 characters)"
        )
    if normalized.lower() in MUTABLE_TAGS:
        issues.append("SCIPILOT_IMAGE_TAG must be immutable; mutable tags are refused")
    if any(marker in normalized.lower() for marker in ("replace", "placeholder", "your-")):
        issues.append("SCIPILOT_IMAGE_TAG is still a placeholder")
    return issues


def validate_environment(
    values: Mapping[str, str], env_path: Path | None = None
) -> tuple[list[str], list[str]]:
    """Return production errors and non-blocking warnings without secret values."""

    issues, warnings = _runtime_configuration_issues(values)

    if values.get("SCIPILOT_ENV", "production").strip().lower() != "production":
        issues.append("SCIPILOT_ENV must be production for this deployment stack")
    if _bool_value(values, "LOCAL_DEMO_MODE", "false") is not False:
        issues.append("LOCAL_DEMO_MODE must be explicitly false")
    if _bool_value(values, "AUTH_AUTO_CONFIRM_EMAIL", "false") is not False:
        issues.append("AUTH_AUTO_CONFIRM_EMAIL must be explicitly false")
    if _bool_value(values, "SCIPILOT_DOCKER_EXECUTION_ENABLED", "false") is not False:
        issues.append(
            "SCIPILOT_DOCKER_EXECUTION_ENABLED must stay false: the web stack does not "
            "mount a Docker socket"
        )
    if _bool_value(values, "SCIPILOT_INSTALL_OCR", "true") is None:
        issues.append("SCIPILOT_INSTALL_OCR must be a boolean")
    ocr_enabled = _bool_value(values, "SCIPILOT_PDF_OCR_ENABLED", "false")
    if ocr_enabled is None:
        issues.append("SCIPILOT_PDF_OCR_ENABLED must be a boolean")
    elif ocr_enabled and not _bool_value(values, "SCIPILOT_INSTALL_OCR", "true"):
        issues.append(
            "SCIPILOT_PDF_OCR_ENABLED requires SCIPILOT_INSTALL_OCR=true"
        )

    image_tag = values.get("SCIPILOT_IMAGE_TAG", "")
    issues.extend(validate_release_tag(image_tag))

    supabase_url = values.get("SUPABASE_URL", "").strip()
    if supabase_url and not _valid_https_origin(supabase_url):
        issues.append("SUPABASE_URL must be an origin-only HTTPS URL in production")

    for name in ("SCIPILOT_LLM_BASE_URL", "XFYUN_KB_BASE_URL"):
        endpoint = values.get(name, "").strip()
        if endpoint and not _valid_secure_endpoint(endpoint, "https"):
            issues.append(f"{name} must be an absolute HTTPS URL in production")

    agent_ws_names = (
        "PROBLEM_DECOMPOSITION_WS_URL",
        "PROJECT_PLANNING_WS_URL",
        "RESULT_INTERPRETATION_WS_URL",
        "CODE_REPRODUCTION_WS_URL",
    )
    for name in agent_ws_names:
        endpoint = values.get(name, "").strip()
        if endpoint and not _valid_secure_endpoint(endpoint, "wss"):
            issues.append(f"{name} must be an absolute WSS URL in production")
    paper_agent_path = values.get("XF_AGENT_WS_PATH", "").strip()
    if paper_agent_path.lower().startswith(
        ("ws://", "wss://")
    ) and not _valid_secure_endpoint(paper_agent_path, "wss"):
        issues.append(
            "XF_AGENT_WS_PATH must use WSS when configured as an absolute URL"
        )

    bind_address = values.get("SCIPILOT_BIND_ADDRESS", "127.0.0.1").strip()
    try:
        ipaddress.ip_address(bind_address)
    except ValueError:
        issues.append("SCIPILOT_BIND_ADDRESS must be an IPv4 or IPv6 address")
    if bind_address not in {"127.0.0.1", "::1"}:
        warnings.append(
            "The public listener is not loopback; terminate TLS and restrict the host firewall"
        )

    try:
        port = int(values.get("SCIPILOT_PUBLIC_PORT", "8080"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        issues.append("SCIPILOT_PUBLIC_PORT must be an integer from 1 to 65535")

    try:
        max_upload_mb = int(values.get("MAX_UPLOAD_MB", "25"))
        if not 1 <= max_upload_mb <= 32:
            raise ValueError
    except ValueError:
        issues.append(
            "MAX_UPLOAD_MB must be between 1 and 32 to match the nginx request limit"
        )

    origins = [
        item.strip()
        for item in values.get("CORS_ORIGINS", "").split(",")
        if item.strip()
    ]
    if not origins:
        issues.append("CORS_ORIGINS must contain at least one production HTTPS origin")
    valid_origins = [origin for origin in origins if _valid_https_origin(origin)]
    invalid_origins = [origin for origin in origins if origin not in valid_origins]
    if invalid_origins:
        issues.append("Every CORS_ORIGINS entry must be an origin-only HTTPS URL")
    if any(_documentation_hostname(origin) for origin in valid_origins):
        issues.append("CORS_ORIGINS still contains a documentation-only hostname")

    reset_url = values.get("PASSWORD_RESET_REDIRECT_URL", "").strip()
    parsed_reset = urlparse(reset_url)
    try:
        reset_port = parsed_reset.port
    except ValueError:
        reset_port = -1
    if (
        parsed_reset.scheme != "https"
        or not parsed_reset.hostname
        or reset_port == -1
        or parsed_reset.username
        or parsed_reset.password
    ):
        issues.append("PASSWORD_RESET_REDIRECT_URL must be an HTTPS URL")
    elif valid_origins and _origin(reset_url) not in {
        _origin(item) for item in valid_origins
    }:
        issues.append("PASSWORD_RESET_REDIRECT_URL must use an allowed CORS origin")
    if parsed_reset.hostname and _documentation_hostname(reset_url):
        issues.append(
            "PASSWORD_RESET_REDIRECT_URL still contains a documentation-only hostname"
        )

    if env_path is not None and os.name != "nt":
        mode = stat.S_IMODE(env_path.stat().st_mode)
        if mode & 0o077:
            issues.append(
                f"Environment file permissions are too broad ({mode:o}); run chmod 600"
            )
    elif env_path is not None:
        warnings.append(
            "Verify deploy/.env ACLs manually on Windows; POSIX mode checks are unavailable"
        )

    # Preserve order while avoiding duplicate messages from shared validators.
    return list(dict.fromkeys(issues)), list(dict.fromkeys(warnings))


def _subprocess_environment(
    values: Mapping[str, str], env_file: Path, image_tag: str | None = None
) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(values)
    environment["SCIPILOT_ENV_FILE"] = str(env_file.resolve())
    if image_tag:
        environment["SCIPILOT_IMAGE_TAG"] = image_tag
    return environment


def _compose_command(env_file: Path) -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "--file",
        str(COMPOSE_FILE),
    ]


def _display_command(command: Sequence[str]) -> str:
    return " ".join(f'"{item}"' if " " in item else item for item in command)


def _run(
    command: Sequence[str],
    *,
    environment: Mapping[str, str],
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    print(f"[RUN] {_display_command(command)}")
    try:
        return subprocess.run(
            list(command),
            cwd=ROOT,
            env=dict(environment),
            check=True,
            text=True,
            capture_output=capture_output,
        )
    except FileNotFoundError as exc:
        raise DeploymentError(f"Required executable is unavailable: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip() if capture_output else ""
        suffix = f": {detail}" if detail else ""
        raise DeploymentError(
            f"Command failed with exit code {exc.returncode}{suffix}"
        ) from exc


def _release_image_references(tag: str) -> tuple[str, str]:
    return (
        f"scipilot-backend:{tag}",
        f"scipilot-frontend:{tag}",
    )


def _assert_release_tag_unused(
    tag: str,
    *,
    environment: Mapping[str, str],
    state: Mapping[str, str | None],
) -> None:
    """Refuse to overwrite a recorded or locally built release identity."""

    if tag in {state.get("current"), state.get("previous")}:
        raise DeploymentError(
            f"Release tag {tag} is already recorded; choose a new immutable tag"
        )

    existing: list[str] = []
    for reference in _release_image_references(tag):
        result = _run(
            ["docker", "image", "ls", "--quiet", "--no-trunc", reference],
            environment=environment,
            capture_output=True,
        )
        if result.stdout.strip():
            existing.append(reference)
    if existing:
        raise DeploymentError(
            "Release tag already has a local image and will not be rebuilt: "
            + ", ".join(existing)
        )


def _version_tuple(raw: str) -> tuple[int, int, int]:
    match = re.search(r"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?", raw)
    if not match:
        raise DeploymentError("Unable to parse the installed Docker component version")
    return tuple(int(part or 0) for part in match.groups())


def _preflight(
    env_file: Path, image_tag: str | None = None
) -> tuple[dict[str, str], dict[str, str]]:
    values = load_env_file(env_file)
    if image_tag:
        values["SCIPILOT_IMAGE_TAG"] = image_tag
    issues, warnings = validate_environment(values, env_file)
    for warning in warnings:
        print(f"[WARN] {warning}")
    if issues:
        raise DeploymentError(
            "Production configuration failed preflight:\n- " + "\n- ".join(issues)
        )

    environment = _subprocess_environment(values, env_file, image_tag)
    docker_version = _run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        environment=environment,
        capture_output=True,
    )
    if _version_tuple(docker_version.stdout) < (24, 0, 0):
        raise DeploymentError("Docker Engine 24 or newer is required")
    compose_version = _run(
        ["docker", "compose", "version", "--short"],
        environment=environment,
        capture_output=True,
    )
    if _version_tuple(compose_version.stdout) < (2, 20, 0):
        raise DeploymentError("Docker Compose 2.20 or newer is required")
    _run(
        [*_compose_command(env_file), "config", "--quiet"],
        environment=environment,
    )
    print("[OK] Production configuration and Docker Compose passed preflight.")
    return values, environment


def _probe_host(bind_address: str) -> str:
    address = ipaddress.ip_address(bind_address)
    if address.is_unspecified:
        return "::1" if address.version == 6 else "127.0.0.1"
    return bind_address


def _format_http_host(host: str) -> str:
    return f"[{host}]" if ":" in host else host


def _verify_endpoint(url: str, deadline: float) -> None:
    last_error = "not attempted"
    while time.monotonic() < deadline:
        try:
            request = Request(url, headers={"User-Agent": "SciPilot-deploy-verify/1"})
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and payload.get("status") == "ok":
                    print(f"[OK] {url}")
                    return
                last_error = f"unexpected response status={response.status}"
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(2)
    raise DeploymentError(f"Health verification failed for {url}: {last_error}")


def verify(values: Mapping[str, str], timeout: int) -> None:
    host = _probe_host(values.get("SCIPILOT_BIND_ADDRESS", "127.0.0.1"))
    port = int(values.get("SCIPILOT_PUBLIC_PORT", "8080"))
    base_url = f"http://{_format_http_host(host)}:{port}"
    deadline = time.monotonic() + timeout
    _verify_endpoint(f"{base_url}/healthz", deadline)
    _verify_endpoint(f"{base_url}/api/v1/health", deadline)
    _verify_endpoint(f"{base_url}/api/v1/readiness", deadline)
    print("[OK] Frontend, backend liveness, and core readiness checks passed.")


def _activate_existing_release(
    *,
    tag: str,
    env_file: Path,
    values: Mapping[str, str],
    timeout: int,
) -> None:
    """Activate a previously built release and verify it through the proxy."""

    target_values = dict(values)
    target_values["SCIPILOT_IMAGE_TAG"] = tag
    environment = _subprocess_environment(target_values, env_file, tag)
    for reference in _release_image_references(tag):
        _run(
            ["docker", "image", "inspect", reference],
            environment=environment,
            capture_output=True,
        )
    _run(
        [
            *_compose_command(env_file),
            "up",
            "--detach",
            "--no-build",
            "--wait",
            "--wait-timeout",
            str(timeout),
            "--remove-orphans",
        ],
        environment=environment,
    )
    verify(target_values, timeout)


def _load_state() -> dict[str, str | None]:
    if not STATE_FILE.is_file():
        return {"current": None, "previous": None}
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise DeploymentError(f"Release state is unreadable: {STATE_FILE}") from exc
    return {
        "current": payload.get("current"),
        "previous": payload.get("previous"),
    }


def _save_state(current: str, previous: str | None) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = STATE_FILE.with_suffix(".tmp")
        payload = {
            "current": current,
            "previous": previous,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary.replace(STATE_FILE)
    except OSError as exc:
        raise DeploymentError("Release state metadata could not be updated") from exc


def release(args: argparse.Namespace) -> None:
    env_file = args.env_file.resolve()
    values, environment = _preflight(env_file, args.tag)
    state = _load_state()
    _assert_release_tag_unused(
        args.tag,
        environment=environment,
        state=state,
    )
    compose = _compose_command(env_file)
    build_command = [*compose, "build"]
    if args.pull:
        build_command.append("--pull")
    _run(build_command, environment=environment)
    previous = state.get("current")
    try:
        _run(
            [
                *compose,
                "up",
                "--detach",
                "--wait",
                "--wait-timeout",
                str(args.timeout),
                "--remove-orphans",
            ],
            environment=environment,
        )
        verify(values, args.timeout)
        _save_state(args.tag, str(previous) if previous else None)
    except DeploymentError as release_error:
        last_known_good = state.get("current")
        if not last_known_good:
            raise DeploymentError(
                f"Release {args.tag} failed and no prior successful release is recorded: "
                f"{release_error}"
            ) from release_error
        try:
            _activate_existing_release(
                tag=str(last_known_good),
                env_file=env_file,
                values=values,
                timeout=args.timeout,
            )
        except DeploymentError as recovery_error:
            raise DeploymentError(
                f"Release {args.tag} failed ({release_error}); automatic recovery to "
                f"{last_known_good} also failed ({recovery_error})"
            ) from recovery_error
        raise DeploymentError(
            f"Release {args.tag} failed; automatically restored last known-good "
            f"release {last_known_good}. Original error: {release_error}"
        ) from release_error
    print(f"[OK] Release {args.tag} is active; rollback metadata was updated.")


def rollback(args: argparse.Namespace) -> None:
    env_file = args.env_file.resolve()
    state = _load_state()
    target = args.tag or state.get("previous")
    if not target:
        raise DeploymentError(
            "No previous release is recorded. Pass an explicit immutable tag with --tag."
        )
    target = str(target)
    values, _environment = _preflight(env_file, target)
    _activate_existing_release(
        tag=target,
        env_file=env_file,
        values=values,
        timeout=args.timeout,
    )
    current = state.get("current")
    _save_state(target, str(current) if current else None)
    print(f"[OK] Rollback to {target} completed and passed health verification.")


def run_preflight(args: argparse.Namespace) -> None:
    _preflight(args.env_file.resolve(), args.tag)


def run_verify(args: argparse.Namespace) -> None:
    env_file = args.env_file.resolve()
    values = load_env_file(env_file)
    state = _load_state()
    active_tag = args.tag or state.get("current") or values.get("SCIPILOT_IMAGE_TAG")
    if active_tag:
        values["SCIPILOT_IMAGE_TAG"] = str(active_tag)
    issues, warnings = validate_environment(values, env_file)
    for warning in warnings:
        print(f"[WARN] {warning}")
    if issues:
        raise DeploymentError(
            "Production configuration failed verification preflight:\n- "
            + "\n- ".join(issues)
        )
    verify(values, args.timeout)


def run_logs(args: argparse.Namespace) -> None:
    env_file = args.env_file.resolve()
    values = load_env_file(env_file)
    state = _load_state()
    tag = state.get("current") or values.get("SCIPILOT_IMAGE_TAG")
    environment = _subprocess_environment(values, env_file, str(tag) if tag else None)
    command = [*_compose_command(env_file), "logs", "--tail", str(args.tail)]
    if args.follow:
        command.append("--follow")
    _run(command, environment=environment)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="production environment file (default: deploy/.env)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight_parser = subparsers.add_parser(
        "preflight", help="validate secrets, safety settings, Docker, and Compose"
    )
    preflight_parser.add_argument(
        "--tag", help="immutable image tag overriding SCIPILOT_IMAGE_TAG"
    )
    preflight_parser.set_defaults(handler=run_preflight)

    release_parser = subparsers.add_parser(
        "release", help="build, start, wait for health, verify, and record a release"
    )
    release_parser.add_argument("--tag", required=True, help="immutable release tag")
    release_parser.add_argument("--pull", action="store_true", help="refresh base images")
    release_parser.add_argument("--timeout", type=int, default=180)
    release_parser.set_defaults(handler=release)

    rollback_parser = subparsers.add_parser(
        "rollback", help="activate a previously built image tag and verify it"
    )
    rollback_parser.add_argument(
        "--tag", help="target tag; defaults to the previously recorded release"
    )
    rollback_parser.add_argument("--timeout", type=int, default=180)
    rollback_parser.set_defaults(handler=rollback)

    verify_parser = subparsers.add_parser(
        "verify", help="probe the frontend and backend through the public listener"
    )
    verify_parser.add_argument("--tag", help="expected active tag for validation")
    verify_parser.add_argument("--timeout", type=int, default=30)
    verify_parser.set_defaults(handler=run_verify)

    logs_parser = subparsers.add_parser(
        "logs", help="read bounded stdout/stderr logs from both services"
    )
    logs_parser.add_argument("--tail", type=int, default=200)
    logs_parser.add_argument("--follow", action="store_true")
    logs_parser.set_defaults(handler=run_logs)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "timeout", 1) <= 0:
        parser.error("--timeout must be positive")
    if getattr(args, "tail", 1) <= 0:
        parser.error("--tail must be positive")
    try:
        args.handler(args)
    except DeploymentError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

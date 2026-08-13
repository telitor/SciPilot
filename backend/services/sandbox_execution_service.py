"""Constrained Docker execution for approved public repository experiments."""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ALLOWED_PROGRAMS = {"python", "python3", "pytest"}
SHELL_META_PATTERN = re.compile(r"[;&|><`\r\n$()]")
SENSITIVE_COMMAND_PATTERN = re.compile(
    r"(?:api[_-]?key|api[_-]?secret|password|passwd|token)",
    re.IGNORECASE,
)
GITHUB_REPOSITORY_PATTERN = re.compile(r"^/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?$")
OUTPUT_EXCLUDES = {".git", ".scipilot-deps", "__pycache__", ".pytest_cache"}
ANALYZABLE_OUTPUT_SUFFIXES = {".csv", ".json", ".xlsx"}
ANALYZABLE_OUTPUT_MEDIA_TYPES = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
MAX_ANALYZABLE_FILE_BYTES = 5 * 1024 * 1024
MAX_ANALYZABLE_TOTAL_BYTES = 20 * 1024 * 1024


class SandboxConfigurationError(RuntimeError):
    """The sandbox runtime is unavailable or disabled."""


class SandboxCommandError(ValueError):
    """The requested command is outside the approved execution policy."""


@dataclass(frozen=True)
class SandboxExecutionResult:
    exit_code: int
    stdout_excerpt: str
    stderr_excerpt: str
    output_files: list[dict[str, Any]]
    environment: dict[str, Any]
    captured_files: list["CapturedResultFile"] = field(default_factory=list)


@dataclass(frozen=True)
class CapturedResultFile:
    name: str
    relative_path: str
    media_type: str
    size_bytes: int
    sha256: str
    content: bytes


def docker_execution_enabled() -> bool:
    return os.getenv("SCIPILOT_DOCKER_EXECUTION_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def validate_public_github_url(repo_url: str) -> str:
    parsed = urlparse(repo_url.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"github.com", "www.github.com"}
        or parsed.username
        or parsed.password
        or parsed.port
        or parsed.query
        or parsed.fragment
        or not GITHUB_REPOSITORY_PATTERN.fullmatch(parsed.path)
    ):
        raise SandboxCommandError("仅支持公开 GitHub HTTPS 仓库地址")
    return f"https://github.com{parsed.path.rstrip('/').removesuffix('.git')}.git"


def parse_approved_command(command: str) -> list[str]:
    cleaned = command.strip()
    if not cleaned or len(cleaned) > 4000:
        raise SandboxCommandError("运行命令不能为空或超过 4000 个字符")
    if SHELL_META_PATTERN.search(cleaned):
        raise SandboxCommandError("运行命令不能包含管道、重定向或 Shell 控制符")
    if SENSITIVE_COMMAND_PATTERN.search(cleaned):
        raise SandboxCommandError("运行命令不能包含密码、Token、API Key 或 Secret")
    try:
        parts = shlex.split(cleaned, posix=True)
    except ValueError as exc:
        raise SandboxCommandError("运行命令的引号格式无效") from exc
    if not parts or parts[0] not in ALLOWED_PROGRAMS:
        raise SandboxCommandError("第一版仅允许 python、python3 或 pytest 命令")
    if parts[0] in {"python", "python3"}:
        if len(parts) < 2:
            raise SandboxCommandError("Python 命令必须指定脚本或模块")
        if parts[1] in {"-c", "-i", "-"}:
            raise SandboxCommandError("不允许执行内联 Python 或交互式命令")
        if parts[1] == "-m":
            if len(parts) < 3 or parts[2] != "pytest":
                raise SandboxCommandError("第一版仅允许 python -m pytest 模块命令")
        elif parts[1].startswith("-") or not parts[1].lower().endswith(".py"):
            raise SandboxCommandError("Python 命令必须运行仓库中的 .py 文件")
    return parts


def _docker_executable() -> str:
    configured = os.getenv("SCIPILOT_DOCKER_BIN", "").strip()
    candidates = [
        configured,
        shutil.which("docker") or "",
        r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise SandboxConfigurationError("Docker CLI 不可用，请安装并启动 Docker Desktop")


def _safe_subprocess_environment() -> dict[str, str]:
    allowed = (
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "HOME",
        "USERPROFILE",
    )
    return {key: os.environ[key] for key in allowed if os.environ.get(key)}


def _excerpt(value: str, limit: int = 50_000) -> str:
    return value[-limit:]


def _run_checked(
    args: list[str],
    *,
    timeout: int,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            env=_safe_subprocess_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SandboxConfigurationError("仓库准备超时") from exc


def _run_container(
    docker: str,
    args: list[str],
    *,
    name: str,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    try:
        return _run_checked([docker, "run", "--name", name, *args], timeout=timeout)
    except SandboxConfigurationError as exc:
        _run_checked([docker, "rm", "-f", name], timeout=20)
        raise SandboxConfigurationError("Docker 受控执行超时") from exc
    finally:
        _run_checked([docker, "rm", "-f", name], timeout=20)


def _workspace_size(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file() and not any(part in OUTPUT_EXCLUDES for part in path.parts):
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total


def _file_snapshot(root: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if not path.is_file() or any(part in OUTPUT_EXCLUDES for part in relative.parts):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[relative.as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def _output_evidence(
    root: Path,
    before: dict[str, tuple[int, int]],
) -> tuple[list[dict[str, Any]], list[CapturedResultFile]]:
    after = _file_snapshot(root)
    changed = [path for path, state in after.items() if before.get(path) != state]
    evidence: list[dict[str, Any]] = []
    captured_files: list[CapturedResultFile] = []
    captured_bytes = 0
    analyzable_bytes = 0
    for relative_path in changed[:50]:
        path = root / relative_path
        try:
            size = path.stat().st_size
            if size > 25 * 1024 * 1024 or captured_bytes + size > 200 * 1024 * 1024:
                continue
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
        except OSError:
            continue
        suffix = path.suffix.lower()
        is_analyzable = suffix in ANALYZABLE_OUTPUT_SUFFIXES
        can_capture = (
            is_analyzable
            and size <= MAX_ANALYZABLE_FILE_BYTES
            and analyzable_bytes + size <= MAX_ANALYZABLE_TOTAL_BYTES
        )
        evidence.append(
            {
                "name": path.name,
                "relative_path": relative_path,
                "size_bytes": size,
                "sha256": digest,
                "media_type": ANALYZABLE_OUTPUT_MEDIA_TYPES.get(suffix),
                "analyzable": can_capture,
            }
        )
        if can_capture:
            captured_files.append(
                CapturedResultFile(
                    name=path.name,
                    relative_path=relative_path,
                    media_type=ANALYZABLE_OUTPUT_MEDIA_TYPES[suffix],
                    size_bytes=size,
                    sha256=digest,
                    content=content,
                )
            )
            analyzable_bytes += size
        captured_bytes += size
    return evidence, captured_files


def _container_limits(workspace: Path, name: str) -> list[str]:
    memory = os.getenv("SCIPILOT_EXECUTION_MEMORY", "2g").strip() or "2g"
    cpus = _bounded_float("SCIPILOT_EXECUTION_CPUS", 2.0, 0.25, 4.0)
    return [
        "--rm",
        "--cpus",
        str(cpus),
        "--memory",
        memory,
        "--pids-limit",
        "256",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=256m",
        "--user",
        "65532:65532",
        "--mount",
        f"type=bind,source={workspace.resolve()},target=/workspace",
        "--workdir",
        "/workspace",
        "--label",
        f"scipilot.run={name}",
    ]


def execute_repository_run(
    *,
    repo_url: str,
    commit_sha: str,
    command: str,
) -> SandboxExecutionResult:
    if not docker_execution_enabled():
        raise SandboxConfigurationError(
            "Docker 受控执行未启用，请设置 SCIPILOT_DOCKER_EXECUTION_ENABLED=true"
        )
    canonical_repo_url = validate_public_github_url(repo_url)
    command_parts = parse_approved_command(command)
    docker = _docker_executable()
    timeout = _bounded_int("SCIPILOT_EXECUTION_TIMEOUT_SECONDS", 120, 30, 120)
    prepare_timeout = _bounded_int(
        "SCIPILOT_EXECUTION_PREPARE_TIMEOUT_SECONDS", 300, 60, 600
    )
    max_workspace_bytes = _bounded_int(
        "SCIPILOT_EXECUTION_MAX_WORKSPACE_MB", 1024, 64, 2048
    ) * 1024 * 1024
    image = os.getenv("SCIPILOT_DOCKER_IMAGE", "python:3.11-slim").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}", image):
        raise SandboxConfigurationError("SCIPILOT_DOCKER_IMAGE 格式无效")

    docker_status = _run_checked([docker, "info"], timeout=20)
    if docker_status.returncode != 0:
        raise SandboxConfigurationError("Docker Desktop 尚未启动或容器引擎不可用")

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="scipilot-experiment-") as temp_dir:
        workspace = Path(temp_dir) / "repository"
        clone = _run_checked(
            [
                "git",
                "-c",
                "credential.helper=",
                "-c",
                "filter.lfs.smudge=",
                "-c",
                "filter.lfs.required=false",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                canonical_repo_url,
                str(workspace),
            ],
            timeout=prepare_timeout,
        )
        if clone.returncode != 0:
            raise SandboxConfigurationError(
                f"公开仓库下载失败：{_excerpt(clone.stderr, 1000)}"
            )
        checkout = _run_checked(
            ["git", "fetch", "--depth", "1", "origin", commit_sha],
            cwd=workspace,
            timeout=prepare_timeout,
        )
        if checkout.returncode == 0:
            checkout = _run_checked(
                ["git", "checkout", "--detach", "FETCH_HEAD"],
                cwd=workspace,
                timeout=60,
            )
        if checkout.returncode != 0:
            raise SandboxCommandError("指定 commit 无法从公开仓库检出")
        if _workspace_size(workspace) > max_workspace_bytes:
            raise SandboxCommandError("仓库超过受控执行空间限制")

        if os.name != "nt":
            workspace.chmod(0o777)

        setup_stdout = ""
        setup_stderr = ""
        requirements = workspace / "requirements.txt"
        if requirements.is_file():
            setup_name = f"scipilot-setup-{uuid.uuid4().hex[:12]}"
            setup = _run_container(
                docker,
                [
                    *_container_limits(workspace, setup_name),
                    "--network",
                    "bridge",
                    image,
                    "python",
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-input",
                    "--target",
                    "/workspace/.scipilot-deps",
                    "-r",
                    "/workspace/requirements.txt",
                ],
                name=setup_name,
                timeout=prepare_timeout,
            )
            setup_stdout = setup.stdout
            setup_stderr = setup.stderr
            if setup.returncode != 0:
                return SandboxExecutionResult(
                    exit_code=setup.returncode,
                    stdout_excerpt=_excerpt(setup_stdout),
                    stderr_excerpt=_excerpt(setup_stderr),
                    output_files=[],
                    environment={
                        "executor": "docker",
                        "image": image,
                        "network": "dependency-setup-only",
                        "phase": "dependency-setup",
                    },
                )
            if _workspace_size(workspace) > max_workspace_bytes:
                raise SandboxCommandError("依赖安装后工作区超过受控执行空间限制")

        before = _file_snapshot(workspace)
        run_name = f"scipilot-run-{uuid.uuid4().hex[:12]}"
        result = _run_container(
            docker,
            [
                *_container_limits(workspace, run_name),
                "--network",
                "none",
                "--env",
                "PYTHONPATH=/workspace/.scipilot-deps",
                image,
                *command_parts,
            ],
            name=run_name,
            timeout=timeout,
        )
        duration_seconds = round(time.monotonic() - started, 3)
        output_files, captured_files = _output_evidence(workspace, before)
        return SandboxExecutionResult(
            exit_code=result.returncode,
            stdout_excerpt=_excerpt(result.stdout),
            stderr_excerpt=_excerpt(result.stderr),
            output_files=output_files,
            environment={
                "executor": "docker",
                "image": image,
                "network": "none",
                "timeout_seconds": timeout,
                "cpu_limit": _bounded_float(
                    "SCIPILOT_EXECUTION_CPUS", 2.0, 0.25, 4.0
                ),
                "memory_limit": os.getenv("SCIPILOT_EXECUTION_MEMORY", "2g"),
                "duration_seconds": duration_seconds,
                "dependencies_installed": requirements.is_file(),
            },
            captured_files=captured_files,
        )

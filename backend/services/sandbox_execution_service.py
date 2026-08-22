"""Constrained Docker execution for approved public repository experiments."""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import shlex
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse


ALLOWED_PROGRAMS = {"python", "python3", "pytest", "Rscript", "julia", "node"}
PROGRAM_SCRIPT_SUFFIXES = {
    "Rscript": (".r",),
    "julia": (".jl",),
    "node": (".js", ".mjs", ".cjs"),
}
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
IMAGE_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}$")
DATASET_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
GPU_DEVICES_PATTERN = re.compile(r"^(?:all|[0-9]+(?:,[0-9]+)*)$")
_GIT_SAFETY_OPTIONS = (
    "-c",
    "credential.helper=",
    "-c",
    "filter.lfs.smudge=",
    "-c",
    "filter.lfs.required=false",
)
_WINDOWS_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
_PROCESS_EXCERPT_BYTES = 50_000


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


@dataclass(frozen=True)
class SandboxExecutionPolicy:
    """Validated caller-selectable execution settings.

    Host paths and GPU access always originate from operator configuration;
    API callers can only select an allow-listed image, dataset ID and device.
    """

    image: str
    dataset_mounts: tuple[tuple[str, Path], ...] = ()
    gpu_devices: str | None = None


def docker_execution_enabled() -> bool:
    return _env_bool("SCIPILOT_DOCKER_EXECUTION_ENABLED")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {
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


def _operator_dataset_mounts() -> dict[str, Path]:
    raw = os.getenv("SCIPILOT_DATASET_MOUNTS_JSON", "{}").strip() or "{}"
    try:
        configured = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SandboxConfigurationError(
            "SCIPILOT_DATASET_MOUNTS_JSON 必须是 JSON 对象"
        ) from exc
    if not isinstance(configured, dict) or len(configured) > 64:
        raise SandboxConfigurationError(
            "SCIPILOT_DATASET_MOUNTS_JSON 必须是至多包含 64 项的 JSON 对象"
        )
    result: dict[str, Path] = {}
    for dataset_id, source in configured.items():
        if not isinstance(dataset_id, str) or not DATASET_ID_PATTERN.fullmatch(dataset_id):
            raise SandboxConfigurationError("数据集 ID 格式无效")
        if not isinstance(source, str) or not source.strip() or "," in source:
            raise SandboxConfigurationError(f"数据集 {dataset_id} 的宿主机路径无效")
        path = Path(source).expanduser().resolve()
        if not path.is_dir():
            raise SandboxConfigurationError(f"数据集 {dataset_id} 的宿主机目录不存在")
        result[dataset_id] = path
    return result


def resolve_execution_policy(
    environment: dict[str, Any] | None = None,
) -> SandboxExecutionPolicy:
    """Resolve a request against operator-owned image, dataset and GPU policy."""

    requested = environment or {}
    default_image = os.getenv("SCIPILOT_DOCKER_IMAGE", "python:3.11-slim").strip()
    raw_allowed_images = os.getenv("SCIPILOT_DOCKER_ALLOWED_IMAGES", default_image)
    allowed_images = {
        value.strip() for value in raw_allowed_images.split(",") if value.strip()
    }
    if not allowed_images or any(
        not IMAGE_REFERENCE_PATTERN.fullmatch(image) for image in allowed_images
    ):
        raise SandboxConfigurationError("Docker 镜像白名单配置无效")
    image_value = requested.get("image", default_image)
    if not isinstance(image_value, str) or image_value.strip() not in allowed_images:
        raise SandboxCommandError("请求的 Docker 镜像不在管理员白名单中")
    image = image_value.strip()

    requested_datasets = requested.get("datasets", [])
    if requested_datasets is None:
        requested_datasets = []
    if (
        not isinstance(requested_datasets, list)
        or len(requested_datasets) > 8
        or any(not isinstance(item, str) for item in requested_datasets)
    ):
        raise SandboxCommandError("datasets 必须是至多包含 8 个数据集 ID 的数组")
    dataset_ids = list(dict.fromkeys(item.strip() for item in requested_datasets))
    if any(not DATASET_ID_PATTERN.fullmatch(item) for item in dataset_ids):
        raise SandboxCommandError("请求的数据集 ID 格式无效")
    configured_datasets = _operator_dataset_mounts() if dataset_ids else {}
    unknown = [item for item in dataset_ids if item not in configured_datasets]
    if unknown:
        raise SandboxCommandError("请求了未获批准的数据集：" + "、".join(unknown))
    dataset_mounts = tuple((item, configured_datasets[item]) for item in dataset_ids)

    gpu_value = requested.get("gpu", False)
    gpu_devices: str | None = None
    if gpu_value not in (False, None, "", "none"):
        if not _env_bool("SCIPILOT_DOCKER_GPU_ENABLED"):
            raise SandboxCommandError("GPU 受控执行尚未由管理员启用")
        gpu_devices = "all" if gpu_value is True else str(gpu_value).strip()
        if not GPU_DEVICES_PATTERN.fullmatch(gpu_devices):
            raise SandboxCommandError("gpu 只能是 true、all 或逗号分隔的设备编号")

    return SandboxExecutionPolicy(
        image=image,
        dataset_mounts=dataset_mounts,
        gpu_devices=gpu_devices,
    )


def validate_execution_environment(environment: dict[str, Any] | None = None) -> None:
    """Validate sandbox selectors early, before a durable job is enqueued."""

    resolve_execution_policy(environment)


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


def _validate_repository_script_path(value: str) -> None:
    """Require an ordinary relative script path inside the checked-out repository."""

    if not value or "\\" in value or ":" in value or "\x00" in value:
        raise SandboxCommandError("脚本路径必须是仓库内的相对 POSIX 路径")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise SandboxCommandError("脚本路径不能离开仓库工作区")
    visible_parts = [part for part in path.parts if part not in {"", "."}]
    if not visible_parts or visible_parts[0] in {".git", ".scipilot-deps"}:
        raise SandboxCommandError("脚本路径必须指向仓库中的普通源文件")


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
        else:
            _validate_repository_script_path(parts[1])
    elif parts[0] == "pytest":
        if any(part in {"--collect-in-virtualenv", "--trace"} for part in parts[1:]):
            raise SandboxCommandError("Pytest 命令包含未获批准的交互或递归选项")
    else:
        if len(parts) < 2 or parts[1].startswith("-"):
            raise SandboxCommandError(f"{parts[0]} 命令必须指定仓库中的脚本文件")
        suffixes = PROGRAM_SCRIPT_SUFFIXES[parts[0]]
        if not parts[1].lower().endswith(suffixes):
            expected = " / ".join(suffixes)
            raise SandboxCommandError(f"{parts[0]} 只能运行 {expected} 脚本")
        _validate_repository_script_path(parts[1])
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
    environment = {key: os.environ[key] for key in allowed if os.environ.get(key)}
    # Repository preparation is deliberately non-interactive and must never
    # invoke Git LFS smudge filters outside the bounded workspace policy.
    environment.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_LFS_SKIP_SMUDGE": "1",
            "GCM_INTERACTIVE": "Never",
        }
    )
    return environment


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


def _terminate_preparation_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                shell=False,
            )
            if process.poll() is None:
                process.kill()
    except (OSError, ProcessLookupError):
        try:
            process.kill()
        except OSError:
            pass


def _run_checked_with_disk_quota(
    args: list[str],
    *,
    timeout: int,
    cwd: Path | None,
    disk_root: Path,
    max_disk_bytes: int,
) -> subprocess.CompletedProcess[str]:
    """Run repository preparation while policing all workspace bytes."""

    if _workspace_size(disk_root) > max_disk_bytes:
        raise SandboxCommandError("仓库准备超过受控执行空间限制")
    process = subprocess.Popen(
        args,
        cwd=cwd,
        env=_safe_subprocess_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        start_new_session=os.name != "nt",
    )
    deadline = time.monotonic() + timeout
    stdout = ""
    stderr = ""
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(args, timeout)
            try:
                stdout, stderr = process.communicate(timeout=min(0.25, remaining))
                break
            except subprocess.TimeoutExpired:
                if _workspace_size(disk_root) > max_disk_bytes:
                    raise SandboxCommandError("仓库准备超过受控执行空间限制")
        if _workspace_size(disk_root) > max_disk_bytes:
            raise SandboxCommandError("仓库准备超过受控执行空间限制")
    except (SandboxCommandError, subprocess.TimeoutExpired) as exc:
        _terminate_preparation_process(process)
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            _terminate_preparation_process(process)
            process.communicate()
        if isinstance(exc, subprocess.TimeoutExpired):
            raise SandboxConfigurationError("仓库准备超时") from exc
        raise
    return subprocess.CompletedProcess(
        args=args,
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _run_streamed_process(
    args: list[str],
    *,
    timeout: int,
    max_output_bytes: int,
    quota_exceeded: Callable[[], bool] | None = None,
    on_limit: Callable[[str], None] | None = None,
) -> tuple[subprocess.CompletedProcess[str], str | None]:
    """Drain untrusted output continuously and retain only bounded tails."""

    process = subprocess.Popen(
        args,
        env=_safe_subprocess_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        shell=False,
        start_new_session=os.name != "nt",
    )
    output_exceeded = threading.Event()
    output_lock = threading.Lock()
    total_output_bytes = 0
    stdout_tail = bytearray()
    stderr_tail = bytearray()

    def drain(stream, tail: bytearray) -> None:
        nonlocal total_output_bytes
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    return
                with output_lock:
                    total_output_bytes += len(chunk)
                    tail.extend(chunk)
                    if len(tail) > _PROCESS_EXCERPT_BYTES:
                        del tail[:-_PROCESS_EXCERPT_BYTES]
                    if total_output_bytes > max_output_bytes:
                        output_exceeded.set()
        except (OSError, ValueError):
            return

    stdout_reader = threading.Thread(
        target=drain,
        args=(process.stdout, stdout_tail),
        name="scipilot-stdout-drain",
        daemon=True,
    )
    stderr_reader = threading.Thread(
        target=drain,
        args=(process.stderr, stderr_tail),
        name="scipilot-stderr-drain",
        daemon=True,
    )
    stdout_reader.start()
    stderr_reader.start()

    reason: str | None = None
    deadline = time.monotonic() + timeout
    next_quota_check = 0.0
    while process.poll() is None:
        now = time.monotonic()
        if output_exceeded.is_set():
            reason = "output"
        elif quota_exceeded is not None and now >= next_quota_check:
            next_quota_check = now + 0.5
            if quota_exceeded():
                reason = "disk"
        elif now >= deadline:
            reason = "timeout"
        if reason is not None:
            if on_limit is not None:
                try:
                    on_limit(reason)
                except Exception:
                    pass
            _terminate_preparation_process(process)
            break
        time.sleep(0.05)

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _terminate_preparation_process(process)
        process.wait(timeout=5)
    stdout_reader.join(timeout=5)
    stderr_reader.join(timeout=5)
    if output_exceeded.is_set() and reason is None:
        reason = "output"
        if on_limit is not None:
            try:
                on_limit(reason)
            except Exception:
                pass
    completed = subprocess.CompletedProcess(
        args=args,
        returncode=process.returncode,
        stdout=bytes(stdout_tail).decode("utf-8", errors="replace"),
        stderr=bytes(stderr_tail).decode("utf-8", errors="replace"),
    )
    return completed, reason


def _run_container(
    docker: str,
    args: list[str],
    *,
    name: str,
    timeout: int,
    disk_root: Path | None = None,
    max_disk_bytes: int | None = None,
) -> subprocess.CompletedProcess[str]:
    stop_monitor = threading.Event()
    quota_exceeded = threading.Event()

    def monitor_disk_quota() -> None:
        if disk_root is None or max_disk_bytes is None:
            return
        while not stop_monitor.wait(0.5):
            if _workspace_size(disk_root) <= max_disk_bytes:
                continue
            quota_exceeded.set()
            try:
                _run_checked([docker, "rm", "-f", name], timeout=20)
            except SandboxConfigurationError:
                pass
            return

    monitor = threading.Thread(
        target=monitor_disk_quota,
        name=f"{name}-disk-quota",
        daemon=True,
    )
    monitor.start()
    try:
        result = _run_checked([docker, "run", "--name", name, *args], timeout=timeout)
    except SandboxConfigurationError as exc:
        raise SandboxConfigurationError("Docker 受控执行超时") from exc
    finally:
        stop_monitor.set()
        monitor.join(timeout=2)
        try:
            _run_checked([docker, "rm", "-f", name], timeout=20)
        except SandboxConfigurationError:
            pass
    if quota_exceeded.is_set():
        raise SandboxCommandError("受控执行超出磁盘配额，容器已终止")
    return result


def _is_reparse_point(file_status: os.stat_result) -> bool:
    return bool(
        _WINDOWS_REPARSE_POINT
        and getattr(file_status, "st_file_attributes", 0) & _WINDOWS_REPARSE_POINT
    )


def _iter_regular_files(
    root: Path,
    *,
    excluded_parts: set[str] | frozenset[str] = frozenset(),
):
    """Yield contained ordinary files without following links or junctions."""

    try:
        resolved_root = root.resolve(strict=True)
    except OSError:
        return
    for current_dir, directory_names, file_names in os.walk(
        resolved_root,
        topdown=True,
        followlinks=False,
    ):
        current = Path(current_dir)
        safe_directories: list[str] = []
        for name in directory_names:
            path = current / name
            try:
                file_status = path.lstat()
            except OSError:
                continue
            if (
                name not in excluded_parts
                and stat.S_ISDIR(file_status.st_mode)
                and not stat.S_ISLNK(file_status.st_mode)
                and not _is_reparse_point(file_status)
            ):
                safe_directories.append(name)
        directory_names[:] = safe_directories

        for name in file_names:
            path = current / name
            try:
                relative = path.relative_to(resolved_root)
                file_status = path.lstat()
            except (OSError, ValueError):
                continue
            if (
                any(part in excluded_parts for part in relative.parts)
                or not stat.S_ISREG(file_status.st_mode)
                or stat.S_ISLNK(file_status.st_mode)
                or _is_reparse_point(file_status)
            ):
                continue
            try:
                resolved_path = path.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if not resolved_path.is_relative_to(resolved_root):
                continue
            yield path, relative, file_status


def _workspace_size(root: Path) -> int:
    """Count every regular workspace byte, including Git and dependencies."""

    return sum(file_status.st_size for _, _, file_status in _iter_regular_files(root))


@contextmanager
def _gpu_slot(gpu_devices: str | None):
    """Reserve a cross-process host GPU slot with an operator-bounded wait."""

    if gpu_devices is None:
        yield None
        return
    configured_dir = os.getenv("SCIPILOT_GPU_SLOT_DIR", "").strip()
    slot_dir = (
        Path(configured_dir).expanduser()
        if configured_dir
        else Path(tempfile.gettempdir()) / "scipilot-gpu-slots"
    ).resolve()
    slot_dir.mkdir(parents=True, exist_ok=True)
    concurrency = _bounded_int("SCIPILOT_GPU_CONCURRENCY", 1, 1, 8)
    wait_seconds = _bounded_int("SCIPILOT_GPU_QUEUE_WAIT_SECONDS", 600, 10, 3600)
    stale_seconds = _bounded_int("SCIPILOT_GPU_SLOT_STALE_SECONDS", 14400, 600, 86400)
    deadline = time.monotonic() + wait_seconds
    acquired: Path | None = None
    while acquired is None and time.monotonic() < deadline:
        for index in range(concurrency):
            candidate = slot_dir / f"slot-{index}.lock"
            try:
                descriptor = os.open(
                    candidate,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError:
                try:
                    is_stale = time.time() - candidate.stat().st_mtime > stale_seconds
                except OSError:
                    is_stale = False
                if is_stale:
                    try:
                        candidate.unlink()
                    except OSError:
                        pass
                continue
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "pid": os.getpid(),
                        "created_at": int(time.time()),
                        "gpu_devices": gpu_devices,
                    },
                    handle,
                )
            acquired = candidate
            break
        if acquired is None:
            time.sleep(0.5)
    if acquired is None:
        raise SandboxConfigurationError("GPU 队列等待超时，请稍后重试")
    try:
        yield acquired.stem
    finally:
        try:
            acquired.unlink()
        except OSError:
            pass


def _file_snapshot(root: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    for _path, relative, file_status in _iter_regular_files(
        root,
        excluded_parts=OUTPUT_EXCLUDES,
    ):
        snapshot[relative.as_posix()] = (
            file_status.st_size,
            file_status.st_mtime_ns,
        )
    return snapshot


def _read_contained_regular_file(
    root: Path,
    path: Path,
    *,
    max_bytes: int,
) -> tuple[bytes, int]:
    """Open one output without following a swapped symlink/reparse point."""

    resolved_root = root.resolve(strict=True)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise OSError("output path is outside the workspace") from exc
    cursor = root
    for part in relative.parts[:-1]:
        cursor = cursor / part
        directory_status = cursor.lstat()
        if (
            not stat.S_ISDIR(directory_status.st_mode)
            or stat.S_ISLNK(directory_status.st_mode)
            or _is_reparse_point(directory_status)
        ):
            raise OSError("output path contains a link or reparse point")

    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or _is_reparse_point(before)
    ):
        raise OSError("output is not a contained regular file")
    try:
        resolved_path = path.resolve(strict=True)
    except RuntimeError as exc:
        raise OSError("output path cannot be resolved safely") from exc
    if not resolved_path.is_relative_to(resolved_root):
        raise OSError("output is outside the workspace")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or _is_reparse_point(opened)
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise OSError("output changed while it was being opened")
        if opened.st_size > max_bytes:
            raise ValueError("output exceeds capture limit")
        content = handle.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError("output exceeds capture limit")
    return content, len(content)


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
        expected_size = after[relative_path][0]
        if (
            expected_size > 25 * 1024 * 1024
            or captured_bytes + expected_size > 200 * 1024 * 1024
        ):
            continue
        try:
            content, size = _read_contained_regular_file(
                root,
                path,
                max_bytes=25 * 1024 * 1024,
            )
            if captured_bytes + size > 200 * 1024 * 1024:
                continue
            digest = hashlib.sha256(content).hexdigest()
        except (OSError, ValueError):
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


def _container_limits(
    workspace: Path,
    name: str,
    *,
    dataset_mounts: tuple[tuple[str, Path], ...] = (),
    gpu_devices: str | None = None,
) -> list[str]:
    memory = os.getenv("SCIPILOT_EXECUTION_MEMORY", "2g").strip() or "2g"
    cpus = _bounded_float("SCIPILOT_EXECUTION_CPUS", 2.0, 0.25, 4.0)
    limits = [
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
    for dataset_id, source in dataset_mounts:
        limits.extend(
            [
                "--mount",
                f"type=bind,source={source},target=/datasets/{dataset_id},readonly",
            ]
        )
    if gpu_devices is not None:
        limits.extend(
            [
                "--gpus",
                "all" if gpu_devices == "all" else f"device={gpu_devices}",
            ]
        )
    return limits


def execute_repository_run(
    *,
    repo_url: str,
    commit_sha: str,
    command: str,
    execution_environment: dict[str, Any] | None = None,
) -> SandboxExecutionResult:
    if not docker_execution_enabled():
        raise SandboxConfigurationError(
            "Docker 受控执行未启用，请设置 SCIPILOT_DOCKER_EXECUTION_ENABLED=true"
        )
    canonical_repo_url = validate_public_github_url(repo_url)
    command_parts = parse_approved_command(command)
    policy = resolve_execution_policy(execution_environment)
    docker = _docker_executable()
    timeout = _bounded_int("SCIPILOT_EXECUTION_TIMEOUT_SECONDS", 120, 30, 120)
    prepare_timeout = _bounded_int(
        "SCIPILOT_EXECUTION_PREPARE_TIMEOUT_SECONDS", 300, 60, 600
    )
    max_workspace_bytes = _bounded_int(
        "SCIPILOT_EXECUTION_MAX_WORKSPACE_MB", 1024, 64, 2048
    ) * 1024 * 1024
    image = policy.image

    docker_status = _run_checked([docker, "info"], timeout=20)
    if docker_status.returncode != 0:
        raise SandboxConfigurationError("Docker Desktop 尚未启动或容器引擎不可用")

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="scipilot-experiment-") as temp_dir:
        preparation_root = Path(temp_dir)
        workspace = Path(temp_dir) / "repository"
        clone = _run_checked_with_disk_quota(
            [
                "git",
                *_GIT_SAFETY_OPTIONS,
                "clone",
                "--filter=blob:none",
                "--depth",
                "1",
                "--single-branch",
                "--no-tags",
                "--no-checkout",
                canonical_repo_url,
                str(workspace),
            ],
            timeout=prepare_timeout,
            cwd=None,
            disk_root=preparation_root,
            max_disk_bytes=max_workspace_bytes,
        )
        if clone.returncode != 0:
            raise SandboxConfigurationError(
                f"公开仓库下载失败：{_excerpt(clone.stderr, 1000)}"
            )
        checkout = _run_checked_with_disk_quota(
            [
                "git",
                *_GIT_SAFETY_OPTIONS,
                "fetch",
                "--depth",
                "1",
                "--no-tags",
                "origin",
                commit_sha,
            ],
            cwd=workspace,
            timeout=prepare_timeout,
            disk_root=preparation_root,
            max_disk_bytes=max_workspace_bytes,
        )
        if checkout.returncode == 0:
            checkout = _run_checked_with_disk_quota(
                [
                    "git",
                    *_GIT_SAFETY_OPTIONS,
                    "checkout",
                    "--detach",
                    "FETCH_HEAD",
                ],
                cwd=workspace,
                timeout=60,
                disk_root=preparation_root,
                max_disk_bytes=max_workspace_bytes,
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
        try:
            requirements_status = requirements.lstat()
            has_requirements = (
                stat.S_ISREG(requirements_status.st_mode)
                and not stat.S_ISLNK(requirements_status.st_mode)
                and not _is_reparse_point(requirements_status)
            )
        except OSError:
            has_requirements = False
        if has_requirements:
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
                disk_root=workspace,
                max_disk_bytes=max_workspace_bytes,
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
        with _gpu_slot(policy.gpu_devices) as gpu_slot:
            result = _run_container(
                docker,
                [
                    *_container_limits(
                        workspace,
                        run_name,
                        dataset_mounts=policy.dataset_mounts,
                        gpu_devices=policy.gpu_devices,
                    ),
                    "--network",
                    "none",
                    "--env",
                    "PYTHONPATH=/workspace/.scipilot-deps",
                    image,
                    *command_parts,
                ],
                name=run_name,
                timeout=timeout,
                disk_root=workspace,
                max_disk_bytes=max_workspace_bytes,
            )
        if _workspace_size(workspace) > max_workspace_bytes:
            raise SandboxCommandError("受控执行结果超过磁盘配额")
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
                "disk_limit_mb": max_workspace_bytes // (1024 * 1024),
                "datasets": [dataset_id for dataset_id, _ in policy.dataset_mounts],
                "gpu": policy.gpu_devices,
                "gpu_slot": gpu_slot,
                "duration_seconds": duration_seconds,
                "dependencies_installed": has_requirements,
            },
            captured_files=captured_files,
        )

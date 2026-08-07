"""Resumable batch uploader for the local paper collection.

Dry-run is the default. Add ``--execute`` to perform remote writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar

from xfyun_knowledge_base import XfyunApiError, XfyunKnowledgeBaseClient
from xfyun_knowledge_base.client import MAX_FILE_BYTES, SUPPORTED_SUFFIXES


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = SCRIPT_DIR / ".env"
DEFAULT_STATE_FILE = SCRIPT_DIR / ".xfyun-upload-state.json"
DEFAULT_BATCH_SIZE = 10
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_RETRY_BASE_DELAY = 2.0
DEFAULT_RETRY_MAX_DELAY = 30.0
RETRYABLE_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}
T = TypeVar("T")


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("必须是大于或等于 0 的整数")
    return parsed


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("必须是大于或等于 1 的整数")
    return parsed


def non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("必须是大于或等于 0 的数字")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须是大于 0 的数字")
    return parsed


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def exception_chain(error: BaseException) -> Iterable[BaseException]:
    """Yield an exception and its explicit/implicit causes without looping."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def is_retryable_error(error: BaseException) -> bool:
    """Identify transient HTTP, proxy, connection and timeout failures."""
    if isinstance(error, TimeoutError):
        # A completed 30-minute vector polling window is not a transport timeout.
        return not str(error).startswith("等待文件向量化超时:")
    if isinstance(error, OSError):
        return True
    if not isinstance(error, XfyunApiError):
        return False
    if error.http_status in RETRYABLE_HTTP_STATUSES:
        return True
    if error.http_status is not None:
        return False

    retryable_names = {
        "ConnectTimeout",
        "ConnectionError",
        "ConnectionResetError",
        "NewConnectionError",
        "ProtocolError",
        "ProxyError",
        "ReadTimeout",
        "ReadTimeoutError",
        "RemoteDisconnected",
        "Timeout",
        "WriteTimeoutError",
    }
    if any(type(item).__name__ in retryable_names for item in exception_chain(error)):
        return True
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "connection aborted",
            "connection reset",
            "proxy",
            "timed out",
            "timeout",
            "write timeout",
            "请求失败",
        )
    )


def is_confirmed_processing_failure(error: BaseException) -> bool:
    """True only when the API explicitly reports vector processing as failed."""
    return isinstance(error, XfyunApiError) and str(error).startswith("文件处理失败:")


def call_with_retry(
    operation: Callable[[], T],
    *,
    label: str,
    max_attempts: int,
    base_delay: float,
    max_delay: float,
    on_attempt: Callable[[int], None] | None = None,
    on_error: Callable[[BaseException, int, bool], None] | None = None,
) -> tuple[T, int]:
    """Run a remote operation with bounded exponential backoff."""
    for attempt in range(1, max_attempts + 1):
        if on_attempt is not None:
            on_attempt(attempt)
        try:
            return operation(), attempt
        except (OSError, TimeoutError, XfyunApiError) as error:
            will_retry = attempt < max_attempts and is_retryable_error(error)
            if on_error is not None:
                on_error(error, attempt, will_retry)
            if not will_retry:
                raise
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            print(
                f"{label} 暂时失败（第 {attempt}/{max_attempts} 次）：{error}；"
                f"{delay:g} 秒后重试",
                file=sys.stderr,
            )
            if delay:
                time.sleep(delay)
    raise AssertionError("retry loop exhausted unexpectedly")


def load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE lines without overriding existing environment variables."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def discover_papers(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        reason = None
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            reason = "unsupported_suffix"
        elif path.stat().st_size > MAX_FILE_BYTES:
            reason = "over_20mb"
        if reason:
            rejected.append({"path": str(path), "reason": reason})
            continue
        accepted.append(
            {
                "path": path,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return accepted, rejected


def deduplicate(
    papers: Iterable[dict[str, Any]], *, include_duplicates: bool
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    first_by_hash: dict[str, dict[str, Any]] = {}
    for paper in papers:
        original = first_by_hash.get(paper["sha256"])
        if original is not None and not include_duplicates:
            duplicate = dict(paper)
            duplicate["duplicate_of"] = str(original["path"])
            duplicates.append(duplicate)
            continue
        first_by_hash.setdefault(paper["sha256"], paper)
        selected.append(paper)
    return selected, duplicates


def load_state(path: Path, repo_id: str) -> dict[str, Any]:
    if not path.is_file():
        return {"version": 2, "repo_id": repo_id, "files": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"状态文件损坏，无法安全续传: {path}: {error}") from error
    if not isinstance(state, dict):
        raise RuntimeError(f"状态文件格式错误，应为 JSON 对象: {path}")
    if state.get("repo_id") != repo_id:
        raise RuntimeError(
            f"状态文件属于其他知识库: {state.get('repo_id')}；当前为 {repo_id}"
        )
    state["version"] = 2
    state.setdefault("files", {})
    if not isinstance(state["files"], dict):
        raise RuntimeError(f"状态文件 files 字段格式错误: {path}")
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = utc_now()
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temp_path.replace(path)


def chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="批量上传论文到讯飞星火知识库")
    parser.add_argument("--execute", action="store_true", help="执行真实上传；默认仅预检")
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="只等待状态文件中已上传的文档完成处理，不上传新文件",
    )
    parser.add_argument(
        "--cleanup-failed",
        action="store_true",
        help="清理状态文件中标记为 failed 的远端文件；需同时传 --execute",
    )
    parser.add_argument(
        "--batch-size",
        type=non_negative_int,
        default=DEFAULT_BATCH_SIZE,
        help=f"每次最多处理的新文件数；0 表示不限制（默认 {DEFAULT_BATCH_SIZE}）",
    )
    parser.add_argument(
        "--limit",
        type=non_negative_int,
        default=None,
        help="兼容参数：覆盖 --batch-size；0 表示不限制",
    )
    parser.add_argument(
        "--include-duplicates",
        action="store_true",
        help="同时上传内容哈希完全相同的重复 PDF",
    )
    parser.add_argument("--no-wait", action="store_true", help="上传后不等待向量化")
    parser.add_argument(
        "--max-attempts",
        type=positive_int,
        default=DEFAULT_MAX_ATTEMPTS,
        help=f"远端操作最多尝试次数（含首次，默认 {DEFAULT_MAX_ATTEMPTS}）",
    )
    parser.add_argument(
        "--retry-base-delay",
        type=non_negative_float,
        default=DEFAULT_RETRY_BASE_DELAY,
        help=f"首次重试等待秒数（默认 {DEFAULT_RETRY_BASE_DELAY:g}）",
    )
    parser.add_argument(
        "--retry-max-delay",
        type=non_negative_float,
        default=DEFAULT_RETRY_MAX_DELAY,
        help=f"指数退避最大等待秒数（默认 {DEFAULT_RETRY_MAX_DELAY:g}）",
    )
    parser.add_argument(
        "--vector-timeout",
        type=positive_float,
        default=1800.0,
        help="单个文件等待向量化的超时秒数（默认 1800）",
    )
    parser.add_argument(
        "--poll-interval",
        type=positive_float,
        default=5.0,
        help="向量化状态轮询间隔秒数（默认 5）",
    )
    parser.add_argument(
        "--retry-uncertain",
        action="store_true",
        help="重试上次进程在上传途中终止的文件；可能造成远端重复，请先核对",
    )
    parser.add_argument(
        "--parse-type",
        choices=("AUTO", "TEXT", "OCR"),
        default="AUTO",
        help="文档解析类型，默认 AUTO",
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.retry_max_delay < args.retry_base_delay:
        raise ValueError("--retry-max-delay 不能小于 --retry-base-delay")
    load_env_file(args.env_file)

    repo_id = os.getenv("XFYUN_KB_REPO_ID", "").strip()
    paper_dir_value = os.getenv("XFYUN_KB_PAPER_DIR", "").strip()
    if not repo_id or not paper_dir_value:
        raise RuntimeError("缺少 XFYUN_KB_REPO_ID 或 XFYUN_KB_PAPER_DIR")
    paper_dir = Path(paper_dir_value)
    if not paper_dir.is_dir():
        raise FileNotFoundError(f"论文目录不存在: {paper_dir}")

    discovered, rejected = discover_papers(paper_dir)
    selected, duplicates = deduplicate(
        discovered, include_duplicates=args.include_duplicates
    )
    total_mb = sum(item["size"] for item in selected) / 1024 / 1024

    print(f"论文目录: {paper_dir}")
    print(f"知识库 ID: {repo_id}")
    print(f"可用文件: {len(discovered)}")
    print(f"哈希重复并跳过: {len(duplicates)}")
    print(f"格式/大小不合规: {len(rejected)}")
    print(f"本次候选: {len(selected)}，合计 {total_mb:.2f}MB")
    for duplicate in duplicates:
        print(
            "  重复跳过: "
            f"{Path(duplicate['path']).name} == {Path(duplicate['duplicate_of']).name}"
        )

    state = load_state(args.state_file, repo_id)
    failed_records = [
        (path, record)
        for path, record in state["files"].items()
        if record.get("status") == "failed" and record.get("file_id")
    ]
    if args.cleanup_failed:
        print(f"待清理 failed 文件: {len(failed_records)}")
        for path, record in failed_records:
            print(f"  {record['file_id']}  {Path(path).name}")
        if not args.execute:
            print("仅列出，未远程删除。确认后添加 --execute。")
            return 0
        client = XfyunKnowledgeBaseClient.from_env()
        failed_ids = [record["file_id"] for _, record in failed_records]
        for batch in chunks(failed_ids, 20):
            client.delete_files(batch)
        for path, _ in failed_records:
            del state["files"][path]
        save_state(args.state_file, state)
        print(f"已清理 {len(failed_ids)} 个 failed 文件及本地断点记录。")
        return 0

    if args.status_only:
        records_by_id = {
            record.get("file_id"): (path, record)
            for path, record in state["files"].items()
            if record.get("file_id") and record.get("status") != "vectored"
        }
        if not records_by_id:
            print("没有待确认状态的已上传文件。")
            return 0
        client = XfyunKnowledgeBaseClient.from_env()
        failures = 0
        for index, (file_id, (path, record)) in enumerate(records_by_id.items(), 1):
            try:
                call_with_retry(
                    lambda: client.wait_until_vectored(
                        [file_id],
                        timeout_seconds=args.vector_timeout,
                        poll_interval_seconds=args.poll_interval,
                    ),
                    label=f"状态确认 {Path(path).name}",
                    max_attempts=args.max_attempts,
                    base_delay=args.retry_base_delay,
                    max_delay=args.retry_max_delay,
                )
                record["status"] = "vectored"
                record.pop("error", None)
                record["updated_at"] = utc_now()
                print(f"[{index}/{len(records_by_id)}] 已向量化: {Path(path).name}")
            except (TimeoutError, XfyunApiError) as error:
                failures += 1
                record["status"] = (
                    "failed" if is_confirmed_processing_failure(error) else "status_error"
                )
                record["error"] = str(error)
                record["updated_at"] = utc_now()
                print(
                    f"[{index}/{len(records_by_id)}] 处理失败: {Path(path).name}: {error}",
                    file=sys.stderr,
                )
            save_state(args.state_file, state)
        print(f"状态确认完成，成功 {len(records_by_id) - failures}，失败 {failures}")
        return 1 if failures else 0

    if failed_records:
        print(
            "存在 failed 断点记录。请先运行 --cleanup-failed 预检，"
            "再用 --cleanup-failed --execute 清理后重试。",
            file=sys.stderr,
        )
        if args.execute:
            return 2

    uncertain = [
        paper
        for paper in selected
        if (
            (record := state["files"].get(str(paper["path"])))
            and record.get("sha256") == paper["sha256"]
            and record.get("status") == "uploading"
            and not record.get("file_id")
        )
    ]
    if uncertain and not args.retry_uncertain:
        print(
            f"检测到 {len(uncertain)} 个上次在上传途中终止的文件，已安全暂停。"
            "请先在远端按文件名核对；确认未上传后添加 --retry-uncertain。",
            file=sys.stderr,
        )

    all_pending = [
        paper
        for paper in selected
        if not (
            (record := state["files"].get(str(paper["path"])))
            and record.get("sha256") == paper["sha256"]
            and record.get("file_id")
            and record.get("status") != "failed"
        )
        and (
            args.retry_uncertain
            or not (
                (record := state["files"].get(str(paper["path"])))
                and record.get("sha256") == paper["sha256"]
                and record.get("status") == "uploading"
                and not record.get("file_id")
            )
        )
    ]
    already_recorded = sum(
        1
        for paper in selected
        if (
            (record := state["files"].get(str(paper["path"])))
            and record.get("sha256") == paper["sha256"]
            and record.get("file_id")
            and record.get("status") != "failed"
        )
    )
    effective_limit = args.limit if args.limit is not None else args.batch_size
    pending = all_pending[:effective_limit] if effective_limit > 0 else all_pending
    deferred = len(all_pending) - len(pending)
    print(
        f"已记录上传: {already_recorded}；本次待上传: {len(pending)}；"
        f"因批次限制延后: {deferred}"
    )

    if not args.execute:
        print("预检完成，未产生远程写入。确认后添加 --execute。")
        return 0
    if not pending:
        print("没有待上传文件。")
        return 0

    client = XfyunKnowledgeBaseClient.from_env()
    uploaded_ids: list[str] = []
    failures = 0
    for index, paper in enumerate(pending, 1):
        path: Path = paper["path"]
        state_key = str(path)
        previous_record = state["files"].get(state_key) or {}
        previous_attempts = int(previous_record.get("attempts") or 0)
        record: dict[str, Any] = {
            "sha256": paper["sha256"],
            "status": "uploading",
            "attempts": previous_attempts,
            "updated_at": utc_now(),
        }
        state["files"][state_key] = record
        save_state(args.state_file, state)

        def on_attempt(attempt: int) -> None:
            record["status"] = "uploading"
            record["attempts"] = previous_attempts + attempt
            record["updated_at"] = utc_now()
            save_state(args.state_file, state)

        def on_upload_error(
            error: BaseException, attempt: int, will_retry: bool
        ) -> None:
            record["status"] = "retrying" if will_retry else "upload_error"
            record["last_error"] = str(error)
            record["last_error_type"] = type(error).__name__
            record["updated_at"] = utc_now()
            save_state(args.state_file, state)

        try:
            response, attempts_used = call_with_retry(
                lambda: client.upload_file(
                    path,
                    repo_ids=[repo_id],
                    parse_type=args.parse_type,
                    need_summary=False,
                ),
                label=f"上传 {path.name}",
                max_attempts=args.max_attempts,
                base_delay=args.retry_base_delay,
                max_delay=args.retry_max_delay,
                on_attempt=on_attempt,
                on_error=on_upload_error,
            )
            file_id = response["data"]["fileId"]
            uploaded_ids.append(file_id)
            state["files"][state_key] = {
                "sha256": paper["sha256"],
                "file_id": file_id,
                "sid": response.get("sid"),
                "status": "uploaded",
                "attempts": previous_attempts + attempts_used,
                "updated_at": utc_now(),
            }
            save_state(args.state_file, state)
            print(f"[{index}/{len(pending)}] 上传成功: {path.name} -> {file_id}")
        except (OSError, ValueError, KeyError, XfyunApiError) as error:
            failures += 1
            record["status"] = "upload_error"
            record["last_error"] = str(error)
            record["last_error_type"] = type(error).__name__
            record["updated_at"] = utc_now()
            save_state(args.state_file, state)
            print(f"[{index}/{len(pending)}] 上传失败: {path.name}: {error}", file=sys.stderr)

    if not args.no_wait:
        records_by_id = {
            record.get("file_id"): (path, record)
            for path, record in state["files"].items()
            if record.get("file_id") in uploaded_ids
        }
        for file_id, (path, record) in records_by_id.items():
            try:
                call_with_retry(
                    lambda: client.wait_until_vectored(
                        [file_id],
                        timeout_seconds=args.vector_timeout,
                        poll_interval_seconds=args.poll_interval,
                    ),
                    label=f"状态确认 {Path(path).name}",
                    max_attempts=args.max_attempts,
                    base_delay=args.retry_base_delay,
                    max_delay=args.retry_max_delay,
                )
                record["status"] = "vectored"
                record.pop("error", None)
                record["updated_at"] = utc_now()
                print(f"已向量化: {Path(path).name}")
            except (TimeoutError, XfyunApiError) as error:
                failures += 1
                record["status"] = (
                    "failed" if is_confirmed_processing_failure(error) else "status_error"
                )
                record["error"] = str(error)
                record["updated_at"] = utc_now()
                print(f"处理失败: {Path(path).name}: {error}", file=sys.stderr)
            save_state(args.state_file, state)

    print(f"本次成功 {len(uploaded_ids)}，失败 {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

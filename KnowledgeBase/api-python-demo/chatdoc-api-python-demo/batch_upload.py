"""Resumable batch uploader for the local paper collection.

Dry-run is the default. Add ``--execute`` to perform remote writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

from xfyun_knowledge_base import XfyunApiError, XfyunKnowledgeBaseClient
from xfyun_knowledge_base.client import MAX_FILE_BYTES, SUPPORTED_SUFFIXES


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = SCRIPT_DIR / ".env"
DEFAULT_STATE_FILE = SCRIPT_DIR / ".xfyun-upload-state.json"


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
        return {"version": 1, "repo_id": repo_id, "files": {}}
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("repo_id") != repo_id:
        raise RuntimeError(
            f"状态文件属于其他知识库: {state.get('repo_id')}；当前为 {repo_id}"
        )
    state.setdefault("files", {})
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
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
    parser.add_argument("--limit", type=int, default=0, help="本次最多上传几篇；0 表示不限制")
    parser.add_argument(
        "--include-duplicates",
        action="store_true",
        help="同时上传内容哈希完全相同的重复 PDF",
    )
    parser.add_argument("--no-wait", action="store_true", help="上传后不等待向量化")
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
                client.wait_until_vectored(
                    [file_id], timeout_seconds=1800, poll_interval_seconds=5
                )
                record["status"] = "vectored"
                print(f"[{index}/{len(records_by_id)}] 已向量化: {Path(path).name}")
            except (TimeoutError, XfyunApiError) as error:
                failures += 1
                record["status"] = "failed"
                record["error"] = str(error)
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

    all_pending = [
        paper
        for paper in selected
        if not (
            (record := state["files"].get(str(paper["path"])))
            and record.get("sha256") == paper["sha256"]
            and record.get("file_id")
            and record.get("status") != "failed"
        )
    ]
    already_recorded = len(selected) - len(all_pending)
    pending = all_pending[: args.limit] if args.limit > 0 else all_pending
    deferred = len(all_pending) - len(pending)
    print(
        f"已记录上传: {already_recorded}；本次待上传: {len(pending)}；"
        f"因 limit 延后: {deferred}"
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
        try:
            response = client.upload_file(
                path,
                repo_ids=[repo_id],
                parse_type=args.parse_type,
                need_summary=False,
            )
            file_id = response["data"]["fileId"]
            uploaded_ids.append(file_id)
            state["files"][str(path)] = {
                "sha256": paper["sha256"],
                "file_id": file_id,
                "sid": response.get("sid"),
                "status": "uploaded",
            }
            save_state(args.state_file, state)
            print(f"[{index}/{len(pending)}] 上传成功: {path.name} -> {file_id}")
        except (OSError, ValueError, KeyError, XfyunApiError) as error:
            failures += 1
            print(f"[{index}/{len(pending)}] 上传失败: {path.name}: {error}", file=sys.stderr)

    if not args.no_wait:
        records_by_id = {
            record.get("file_id"): (path, record)
            for path, record in state["files"].items()
            if record.get("file_id") in uploaded_ids
        }
        for file_id, (path, record) in records_by_id.items():
            try:
                client.wait_until_vectored(
                    [file_id], timeout_seconds=1800, poll_interval_seconds=5
                )
                record["status"] = "vectored"
                print(f"已向量化: {Path(path).name}")
            except (TimeoutError, XfyunApiError) as error:
                failures += 1
                record["status"] = "failed"
                record["error"] = str(error)
                print(f"处理失败: {Path(path).name}: {error}", file=sys.stderr)
            save_state(args.state_file, state)

    print(f"本次成功 {len(uploaded_ids)}，失败 {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Minimal backend integration example; credentials come from environment variables."""

from __future__ import annotations

import argparse
import os

from xfyun_knowledge_base import XfyunKnowledgeBaseClient


def main() -> None:
    parser = argparse.ArgumentParser(description="讯飞星辰知识库 API 示例")
    parser.add_argument("file", help="待上传的本地文档")
    parser.add_argument("question", help="要询问的问题")
    parser.add_argument(
        "--repo-id",
        default=os.getenv("XFYUN_KB_REPO_ID"),
        help="已有知识库 ID；默认读取 XFYUN_KB_REPO_ID，不传则按文件问答",
    )
    args = parser.parse_args()

    client = XfyunKnowledgeBaseClient.from_env()
    uploaded = client.upload_file(
        args.file,
        repo_ids=[args.repo_id] if args.repo_id else [],
        need_summary=False,
    )
    file_id = uploaded["data"]["fileId"]
    client.wait_until_vectored([file_id])

    request = client.build_chat_request(
        [{"role": "user", "content": args.question}],
        repo_ids=[args.repo_id] if args.repo_id else [],
        file_ids=[] if args.repo_id else [file_id],
    )
    for frame in client.iter_chat(request):
        if frame.get("status") != 99:
            print(frame.get("content") or "", end="", flush=True)
    print()


if __name__ == "__main__":
    main()

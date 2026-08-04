"""Compatibility helper for the official question-and-answer demo."""

from collections.abc import Iterator, Sequence
from typing import Any

from xfyun_knowledge_base import XfyunKnowledgeBaseClient


def ask_document(
    question: str,
    *,
    repo_ids: Sequence[str] = (),
    file_ids: Sequence[str] = (),
    client: XfyunKnowledgeBaseClient | None = None,
) -> Iterator[dict[str, Any]]:
    api = client or XfyunKnowledgeBaseClient.from_env()
    request = api.build_chat_request(
        [{"role": "user", "content": question}],
        repo_ids=repo_ids,
        file_ids=file_ids,
    )
    return api.iter_chat(request)

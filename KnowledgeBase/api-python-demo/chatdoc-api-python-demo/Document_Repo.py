"""Compatibility helpers for the official repository demo."""

from typing import Any, Sequence

from xfyun_knowledge_base import XfyunKnowledgeBaseClient


def create_repository(
    repo_name: str,
    *,
    repo_desc: str = "",
    repo_tags: str = "",
    client: XfyunKnowledgeBaseClient | None = None,
) -> dict[str, Any]:
    api = client or XfyunKnowledgeBaseClient.from_env()
    return api.create_repository(
        repo_name, repo_desc=repo_desc, repo_tags=repo_tags
    )


def add_files(
    repo_id: str,
    file_ids: Sequence[str],
    *,
    client: XfyunKnowledgeBaseClient | None = None,
) -> dict[str, Any]:
    api = client or XfyunKnowledgeBaseClient.from_env()
    return api.add_repository_files(repo_id, file_ids)


def remove_files(
    repo_id: str,
    file_ids: Sequence[str],
    *,
    client: XfyunKnowledgeBaseClient | None = None,
) -> dict[str, Any]:
    api = client or XfyunKnowledgeBaseClient.from_env()
    return api.remove_repository_files(repo_id, file_ids)

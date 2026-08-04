"""Compatibility entry for the official upload demo.

New backend code should import ``XfyunKnowledgeBaseClient`` directly.
"""

from pathlib import Path
from typing import Any, Sequence

from xfyun_knowledge_base import XfyunKnowledgeBaseClient


def upload_document(
    file_path: str | Path,
    *,
    repo_ids: Sequence[str] = (),
    client: XfyunKnowledgeBaseClient | None = None,
) -> dict[str, Any]:
    api = client or XfyunKnowledgeBaseClient.from_env()
    return api.upload_file(file_path, repo_ids=repo_ids)

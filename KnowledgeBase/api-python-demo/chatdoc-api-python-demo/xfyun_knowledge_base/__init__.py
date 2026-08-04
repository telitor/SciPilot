"""Reusable client for the iFlytek Spark Knowledge Base API."""

from .client import (
    ChatResult,
    XfyunApiError,
    XfyunKnowledgeBaseClient,
    XfyunKnowledgeBaseSettings,
)

__all__ = [
    "ChatResult",
    "XfyunApiError",
    "XfyunKnowledgeBaseClient",
    "XfyunKnowledgeBaseSettings",
]

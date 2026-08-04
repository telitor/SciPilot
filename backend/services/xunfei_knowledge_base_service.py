"""Backend-only client for the iFlytek Spark ChatDoc knowledge base API."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Sequence

import requests


class XunfeiKnowledgeBaseError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        sid: str | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.sid = sid
        self.http_status = http_status


@dataclass(frozen=True)
class XunfeiKnowledgeBaseSettings:
    app_id: str
    api_secret: str
    repo_id: str
    base_url: str = "https://chatdoc.xfyun.cn"
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 600.0

    @classmethod
    def from_env(cls) -> "XunfeiKnowledgeBaseSettings":
        values = {
            "app_id": os.getenv("XFYUN_KB_APP_ID", "").strip(),
            "api_secret": os.getenv("XFYUN_KB_API_SECRET", "").strip(),
            "repo_id": os.getenv("XFYUN_KB_REPO_ID", "").strip(),
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            env_names = {
                "app_id": "XFYUN_KB_APP_ID",
                "api_secret": "XFYUN_KB_API_SECRET",
                "repo_id": "XFYUN_KB_REPO_ID",
            }
            raise XunfeiKnowledgeBaseError(
                "缺少星火知识库配置: "
                + ", ".join(env_names[name] for name in missing)
            )
        return cls(
            **values,
            base_url=os.getenv(
                "XFYUN_KB_BASE_URL", "https://chatdoc.xfyun.cn"
            ).rstrip("/"),
            connect_timeout_seconds=float(
                os.getenv("XFYUN_KB_CONNECT_TIMEOUT", "10")
            ),
            read_timeout_seconds=float(os.getenv("XFYUN_KB_READ_TIMEOUT", "600")),
        )


@dataclass
class XunfeiKnowledgeAnswer:
    content: str = ""
    reasoning_content: str = ""
    sid: str | None = None
    reference_frames: list[dict[str, Any]] = field(default_factory=list)


def xunfei_knowledge_base_mode() -> str:
    mode = os.getenv("XFYUN_KB_MODE", "off").strip().lower()
    return mode if mode in {"off", "fallback", "prefer"} else "off"


def is_xunfei_knowledge_base_configured() -> bool:
    return all(
        os.getenv(name, "").strip()
        for name in ("XFYUN_KB_APP_ID", "XFYUN_KB_API_SECRET", "XFYUN_KB_REPO_ID")
    )


class XunfeiKnowledgeBaseClient:
    def __init__(
        self,
        settings: XunfeiKnowledgeBaseSettings,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self._session = session or requests.Session()

    @classmethod
    def from_env(cls) -> "XunfeiKnowledgeBaseClient":
        return cls(XunfeiKnowledgeBaseSettings.from_env())

    @staticmethod
    def make_signature(app_id: str, api_secret: str, timestamp: int | str) -> str:
        timestamp_text = str(timestamp)
        auth = hashlib.md5(f"{app_id}{timestamp_text}".encode("utf-8")).hexdigest()
        digest = hmac.new(
            api_secret.encode("utf-8"),
            auth.encode("utf-8"),
            hashlib.sha1,
        ).digest()
        return base64.b64encode(digest).decode("ascii")

    def auth_headers(self, timestamp: int | None = None) -> dict[str, str]:
        current_timestamp = timestamp if timestamp is not None else int(time.time())
        return {
            "appId": self.settings.app_id,
            "timeStamp": str(current_timestamp),
            "signature": self.make_signature(
                self.settings.app_id,
                self.settings.api_secret,
                current_timestamp,
            ),
        }

    def build_chat_request(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        top_n: int = 6,
        thinking_output: bool = False,
        retrieval_filter_policy: str = "REGULAR",
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        if not messages:
            raise ValueError("messages 不能为空")
        if not 1 <= top_n <= 20:
            raise ValueError("top_n 必须在 [1, 20] 范围内")
        if not 0 <= temperature <= 1:
            raise ValueError("temperature 必须在 [0, 1] 范围内")
        return {
            "repoIds": [self.settings.repo_id],
            "topN": top_n,
            "thinkingOutput": thinking_output,
            "messages": [dict(message) for message in messages],
            "chatExtends": {
                "retrievalFilterPolicy": retrieval_filter_policy,
                "wikiPromptTpl": "仅根据知识库内容回答；资料不足时明确说明，不得编造来源。",
                "temperature": temperature,
                "outputType": "plain",
            },
        }

    def iter_chat(self, request_body: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
        headers = {
            **self.auth_headers(),
            "Accept": "text/event-stream",
            "Content-Type": "application/json; charset=utf-8",
        }
        try:
            response = self._session.post(
                f"{self.settings.base_url}/openapi/v2/chat",
                json=dict(request_body),
                headers=headers,
                timeout=(
                    self.settings.connect_timeout_seconds,
                    self.settings.read_timeout_seconds,
                ),
                stream=True,
            )
        except requests.Timeout as exc:
            raise XunfeiKnowledgeBaseError("星火知识库响应超时") from exc
        except requests.RequestException as exc:
            raise XunfeiKnowledgeBaseError(f"星火知识库请求失败: {exc}") from exc

        try:
            if not 200 <= response.status_code < 300:
                raise self._response_error(response)
            response.encoding = "utf-8"
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = (
                    raw_line.decode("utf-8")
                    if isinstance(raw_line, bytes)
                    else raw_line
                ).strip()
                if not line or line.startswith(":") or line.startswith("event:"):
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if not line or line == "[DONE]":
                    continue
                try:
                    frame = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise XunfeiKnowledgeBaseError(
                        f"无法解析星火知识库数据帧: {line[:200]}"
                    ) from exc
                if frame.get("code", 0) != 0:
                    raise XunfeiKnowledgeBaseError(
                        frame.get("message") or frame.get("desc") or "星火知识库问答失败",
                        code=frame.get("code"),
                        sid=frame.get("sid"),
                        http_status=response.status_code,
                    )
                yield frame
        finally:
            response.close()

    def chat(self, request_body: Mapping[str, Any]) -> XunfeiKnowledgeAnswer:
        result = XunfeiKnowledgeAnswer()
        for frame in self.iter_chat(request_body):
            result.sid = frame.get("sid") or result.sid
            if frame.get("status") == 99:
                result.reference_frames.append(frame)
                continue
            result.content += str(frame.get("content") or "")
            result.reasoning_content += str(frame.get("reasoning_content") or "")
        result.content = result.content.strip()
        result.reasoning_content = result.reasoning_content.strip()
        if not result.content:
            raise XunfeiKnowledgeBaseError(
                "星火知识库没有返回回答正文", sid=result.sid
            )
        return result

    @staticmethod
    def _response_error(response: requests.Response) -> XunfeiKnowledgeBaseError:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return XunfeiKnowledgeBaseError(
            payload.get("desc")
            or payload.get("message")
            or f"星火知识库 API HTTP {response.status_code}",
            code=payload.get("code"),
            sid=payload.get("sid"),
            http_status=response.status_code,
        )


def _parse_file_references(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for frame in frames:
        file_refer = frame.get("fileRefer") or {}
        if isinstance(file_refer, str):
            try:
                file_refer = json.loads(file_refer)
            except json.JSONDecodeError:
                file_refer = {}
        if not isinstance(file_refer, dict):
            continue
        for file_id, chunk_indexes in file_refer.items():
            indexes = chunk_indexes if isinstance(chunk_indexes, list) else [chunk_indexes]
            for chunk_index in indexes:
                key = (str(file_id), str(chunk_index))
                if key in seen:
                    continue
                seen.add(key)
                citations.append(
                    {
                        "index": len(citations) + 1,
                        "document_id": str(file_id),
                        "chunk_id": f"{file_id}:{chunk_index}",
                        "title": f"星火知识库文档 {file_id}",
                        "chunk_index": chunk_index,
                        "source_type": "xunfei-chatdoc",
                        "source_url": None,
                        "file_name": None,
                        "score": None,
                        "excerpt": "星火知识库返回的引用片段",
                    }
                )
    return citations


def ask_xunfei_knowledge_base(
    message: str,
    *,
    top_n: int | None = None,
    thinking_output: bool = False,
) -> dict[str, Any]:
    client = XunfeiKnowledgeBaseClient.from_env()
    request = client.build_chat_request(
        [{"role": "user", "content": message}],
        top_n=top_n or int(os.getenv("XFYUN_KB_TOP_N", "6")),
        thinking_output=thinking_output,
        retrieval_filter_policy=os.getenv(
            "XFYUN_KB_RETRIEVAL_FILTER_POLICY", "REGULAR"
        ),
        temperature=float(os.getenv("XFYUN_KB_TEMPERATURE", "0.2")),
    )
    result = client.chat(request)
    return {
        "reply": result.content,
        "reasoning": result.reasoning_content,
        "citations": _parse_file_references(result.reference_frames),
        "sid": result.sid,
        "reference_frames": result.reference_frames,
    }

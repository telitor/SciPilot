"""Backend-friendly iFlytek Spark Knowledge Base API client.

Official API documentation:
https://www.xfyun.cn/doc/spark/ChatDoc-API.html
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import requests


SUPPORTED_SUFFIXES = {
    ".txt",
    ".md",
    ".doc",
    ".docx",
    ".pdf",
    ".xls",
    ".xlsx",
    ".csv",
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".ppt",
    ".pptx",
}
MAX_FILE_BYTES = 20 * 1024 * 1024


class XfyunApiError(RuntimeError):
    """Raised when HTTP transport or the API business code indicates failure."""

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        sid: str | None = None,
        http_status: int | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.sid = sid
        self.http_status = http_status
        self.payload = dict(payload or {})


@dataclass(frozen=True)
class XfyunKnowledgeBaseSettings:
    app_id: str
    api_secret: str
    base_url: str = "https://chatdoc.xfyun.cn"
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 600.0

    @classmethod
    def from_env(cls) -> "XfyunKnowledgeBaseSettings":
        app_id = os.getenv("XFYUN_KB_APP_ID", "").strip()
        api_secret = os.getenv("XFYUN_KB_API_SECRET", "").strip()
        if not app_id or not api_secret:
            raise RuntimeError(
                "缺少 XFYUN_KB_APP_ID 或 XFYUN_KB_API_SECRET 环境变量"
            )
        return cls(
            app_id=app_id,
            api_secret=api_secret,
            base_url=os.getenv(
                "XFYUN_KB_BASE_URL", "https://chatdoc.xfyun.cn"
            ).rstrip("/"),
            connect_timeout_seconds=float(
                os.getenv("XFYUN_KB_CONNECT_TIMEOUT", "10")
            ),
            read_timeout_seconds=float(os.getenv("XFYUN_KB_READ_TIMEOUT", "600")),
        )


@dataclass
class ChatResult:
    content: str = ""
    reasoning_content: str = ""
    sid: str | None = None
    references: list[dict[str, Any]] = field(default_factory=list)
    frames: list[dict[str, Any]] = field(default_factory=list)


class XfyunKnowledgeBaseClient:
    """Synchronous client intended to be owned and reused by a backend service."""

    def __init__(
        self,
        settings: XfyunKnowledgeBaseSettings,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self._session = session or requests.Session()

    @classmethod
    def from_env(cls) -> "XfyunKnowledgeBaseClient":
        return cls(XfyunKnowledgeBaseSettings.from_env())

    @staticmethod
    def make_signature(app_id: str, api_secret: str, timestamp: int | str) -> str:
        timestamp_text = str(timestamp)
        auth = hashlib.md5(
            f"{app_id}{timestamp_text}".encode("utf-8")
        ).hexdigest()
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

    def upload_file(
        self,
        file_path: str | Path,
        *,
        repo_ids: Sequence[str] = (),
        parse_type: str = "AUTO",
        step_by_step: bool = False,
        need_summary: bool = True,
        callback_url: str | None = None,
    ) -> dict[str, Any]:
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"上传文件不存在: {path}")
        self._validate_upload(path.name, path.stat().st_size)

        multipart: list[tuple[str, tuple[Any, ...]]] = [
            ("parseType", (None, parse_type)),
            ("stepByStep", (None, str(step_by_step).lower())),
            ("needSummary", (None, str(need_summary).lower())),
        ]
        multipart.extend(("repoIds", (None, repo_id)) for repo_id in repo_ids)
        if callback_url:
            multipart.append(("callbackUrl", (None, callback_url)))

        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as file_handle:
            multipart.insert(0, ("file", (path.name, file_handle, content_type)))
            return self._request_json(
                "POST",
                "/openapi/v1/file/upload",
                files=multipart,
            )

    def upload_url(
        self,
        url: str,
        file_name: str,
        *,
        repo_ids: Sequence[str] = (),
        parse_type: str = "AUTO",
        step_by_step: bool = False,
        need_summary: bool = True,
        callback_url: str | None = None,
    ) -> dict[str, Any]:
        self._validate_upload(file_name, None)
        multipart: list[tuple[str, tuple[None, str]]] = [
            ("url", (None, url)),
            ("fileName", (None, file_name)),
            ("parseType", (None, parse_type)),
            ("stepByStep", (None, str(step_by_step).lower())),
            ("needSummary", (None, str(need_summary).lower())),
        ]
        multipart.extend(("repoIds", (None, repo_id)) for repo_id in repo_ids)
        if callback_url:
            multipart.append(("callbackUrl", (None, callback_url)))
        return self._request_json(
            "POST",
            "/openapi/v1/file/upload",
            files=multipart,
        )

    def file_status(self, file_ids: Sequence[str]) -> dict[str, Any]:
        ids = self._require_ids(file_ids, "file_ids")
        return self._request_json(
            "POST",
            "/openapi/v1/file/status",
            data={"fileIds": ",".join(ids)},
        )

    def delete_files(self, file_ids: Sequence[str]) -> dict[str, Any]:
        """Delete file resources and their vector data from the current AppID."""
        ids = self._require_ids(file_ids, "file_ids")
        return self._request_json(
            "POST",
            "/openapi/v1/file/del",
            data=[("fileIds", file_id) for file_id in ids],
        )

    def wait_until_vectored(
        self,
        file_ids: Sequence[str],
        *,
        timeout_seconds: float = 600,
        poll_interval_seconds: float = 3,
    ) -> dict[str, Any]:
        ids = self._require_ids(file_ids, "file_ids")
        deadline = time.monotonic() + timeout_seconds
        while True:
            response = self.file_status(ids)
            statuses = {
                item.get("fileId"): item.get("fileStatus")
                for item in response.get("data") or []
            }
            failed = [file_id for file_id, status in statuses.items() if status == "failed"]
            if failed:
                raise XfyunApiError(
                    f"文件处理失败: {', '.join(failed)}",
                    code=response.get("code"),
                    sid=response.get("sid"),
                    payload=response,
                )
            if statuses and all(statuses.get(file_id) == "vectored" for file_id in ids):
                return response
            if time.monotonic() >= deadline:
                detail = ", ".join(
                    f"{file_id}={statuses.get(file_id, 'unknown')}" for file_id in ids
                )
                raise TimeoutError(f"等待文件向量化超时: {detail}")
            time.sleep(poll_interval_seconds)

    def create_repository(
        self,
        repo_name: str,
        *,
        repo_desc: str = "",
        repo_tags: str = "",
    ) -> dict[str, Any]:
        if not repo_name.strip():
            raise ValueError("repo_name 不能为空")
        return self._request_json(
            "POST",
            "/openapi/v1/repo/create",
            json_body={
                "repoName": repo_name,
                "repoDesc": repo_desc,
                "repoTags": repo_tags,
            },
        )

    def add_repository_files(
        self, repo_id: str, file_ids: Sequence[str]
    ) -> dict[str, Any]:
        return self._repository_file_operation(
            "/openapi/v1/repo/file/add", repo_id, file_ids
        )

    def remove_repository_files(
        self, repo_id: str, file_ids: Sequence[str]
    ) -> dict[str, Any]:
        return self._repository_file_operation(
            "/openapi/v1/repo/file/remove", repo_id, file_ids
        )

    def delete_repository(
        self, repo_id: str, *, delete_files: bool = False
    ) -> dict[str, Any]:
        self._require_text(repo_id, "repo_id")
        path = (
            "/openapi/v1/repo/del-with-files"
            if delete_files
            else "/openapi/v1/repo/del"
        )
        return self._request_json("POST", path, data={"repoId": repo_id})

    def build_chat_request(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        repo_ids: Sequence[str] = (),
        file_ids: Sequence[str] = (),
        top_n: int = 6,
        llm: str | None = None,
        thinking_output: bool = False,
        retrieval_filter_policy: str = "REGULAR",
        wiki_prompt_template: str = "根据知识库内容回答用户的问题",
        temperature: float = 0.2,
        output_type: str = "plain",
    ) -> dict[str, Any]:
        if bool(repo_ids) == bool(file_ids):
            raise ValueError("repo_ids 与 file_ids 必须且只能传一个")
        if not messages:
            raise ValueError("messages 不能为空")
        if not 0 <= temperature <= 1:
            raise ValueError("temperature 必须在 [0, 1] 范围内")

        payload: dict[str, Any] = {
            "topN": top_n,
            "thinkingOutput": thinking_output,
            "messages": [dict(message) for message in messages],
            "chatExtends": {
                "retrievalFilterPolicy": retrieval_filter_policy,
                "wikiPromptTpl": wiki_prompt_template,
                "temperature": temperature,
                "outputType": output_type,
            },
        }
        payload["repoIds" if repo_ids else "fileIds"] = list(repo_ids or file_ids)
        if llm:
            payload["llm"] = llm
        return payload

    def iter_chat(self, request_body: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
        headers = self.auth_headers()
        headers.update(
            {
                "Accept": "text/event-stream",
                "Content-Type": "application/json; charset=utf-8",
            }
        )
        url = self._url("/openapi/v2/chat")
        try:
            response = self._session.post(
                url,
                json=dict(request_body),
                headers=headers,
                timeout=self._timeout,
                stream=True,
            )
        except requests.RequestException as exc:
            raise XfyunApiError(f"讯飞知识库问答请求失败: {exc}") from exc

        try:
            if not 200 <= response.status_code < 300:
                raise self._http_error(response)
            response.encoding = "utf-8"
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                line = line.strip()
                if not line or line.startswith(":") or line.startswith("event:"):
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if not line or line == "[DONE]":
                    continue
                try:
                    frame = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise XfyunApiError(f"无法解析 SSE 数据帧: {line[:200]}") from exc
                if frame.get("code", 0) != 0:
                    raise XfyunApiError(
                        frame.get("message") or "讯飞知识库问答失败",
                        code=frame.get("code"),
                        sid=frame.get("sid"),
                        http_status=response.status_code,
                        payload=frame,
                    )
                yield frame
        finally:
            response.close()

    def chat(self, request_body: Mapping[str, Any]) -> ChatResult:
        result = ChatResult()
        for frame in self.iter_chat(request_body):
            result.frames.append(frame)
            result.sid = frame.get("sid") or result.sid
            status = frame.get("status")
            if status == 99:
                result.references.append(frame)
                continue
            result.content += frame.get("content") or ""
            result.reasoning_content += frame.get("reasoning_content") or ""
        return result

    @property
    def _timeout(self) -> tuple[float, float]:
        return (
            self.settings.connect_timeout_seconds,
            self.settings.read_timeout_seconds,
        )

    def _repository_file_operation(
        self, path: str, repo_id: str, file_ids: Sequence[str]
    ) -> dict[str, Any]:
        self._require_text(repo_id, "repo_id")
        ids = self._require_ids(file_ids, "file_ids")
        if len(ids) > 20:
            raise ValueError("单次最多操作 20 个文件")
        return self._request_json(
            "POST",
            path,
            json_body={"repoId": repo_id, "fileIds": ids},
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        data: Any = None,
        files: Any = None,
    ) -> dict[str, Any]:
        try:
            response = self._session.request(
                method,
                self._url(path),
                headers=self.auth_headers(),
                json=dict(json_body) if json_body is not None else None,
                data=data,
                files=files,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise XfyunApiError(f"讯飞知识库 API 请求失败: {exc}") from exc

        if not 200 <= response.status_code < 300:
            raise self._http_error(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise XfyunApiError(
                "讯飞知识库 API 返回了非 JSON 响应",
                http_status=response.status_code,
            ) from exc
        if payload.get("code", 0) != 0:
            raise XfyunApiError(
                payload.get("desc") or payload.get("message") or "讯飞知识库 API 调用失败",
                code=payload.get("code"),
                sid=payload.get("sid"),
                http_status=response.status_code,
                payload=payload,
            )
        return payload

    def _http_error(self, response: requests.Response) -> XfyunApiError:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        message = (
            payload.get("desc")
            or payload.get("message")
            or f"讯飞知识库 API HTTP {response.status_code}"
        )
        return XfyunApiError(
            message,
            code=payload.get("code"),
            sid=payload.get("sid"),
            http_status=response.status_code,
            payload=payload,
        )

    def _url(self, path: str) -> str:
        return f"{self.settings.base_url.rstrip('/')}/{path.lstrip('/')}"

    @staticmethod
    def _validate_upload(file_name: str, size: int | None) -> None:
        suffix = Path(file_name).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError(f"不支持的文档格式: {suffix or '无扩展名'}")
        if size is not None and size > MAX_FILE_BYTES:
            raise ValueError("文档大小不能超过 20MB")

    @staticmethod
    def _require_ids(values: Iterable[str], name: str) -> list[str]:
        result = [value.strip() for value in values if value and value.strip()]
        if not result:
            raise ValueError(f"{name} 不能为空")
        return result

    @staticmethod
    def _require_text(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} 不能为空")

"""Backend-only client for the iFlytek Spark ChatDoc knowledge base API.

This module deliberately has no database dependency.  Repository metadata,
document state, retrieval results, and answers all come from Spark ChatDoc.
Credentials are read from the backend process environment and never returned
to callers or included in raised error messages.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import requests
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


PROVIDER_NAME = "xunfei-chatdoc"
DEFAULT_BASE_URL = "https://chatdoc.xfyun.cn"
MAX_FILE_BYTES = 20 * 1024 * 1024
RETRIEVAL_FILTER_POLICIES = frozenset({"STRICT", "REGULAR", "LENIENT", "OFF"})
QUERY_REWRITE_NOISE = (
    "请问",
    "请帮我",
    "帮我",
    "能否",
    "可以",
    "这些论文中",
    "这篇论文中",
    "这篇论文",
    "本文中",
    "论文中",
)
QUERY_REWRITE_PHRASES = (
    ("主要运用了什么算法", "核心算法 方法 模型"),
    ("主要使用了什么算法", "核心算法 方法 模型"),
    ("使用了哪些算法", "算法 方法 模型"),
    ("有什么创新点", "创新点 主要贡献"),
    ("有哪些创新点", "创新点 主要贡献"),
    ("实验结果怎么样", "实验结果 评价指标 对比"),
    ("有哪些不足", "局限性 不足"),
    ("有什么不足", "局限性 不足"),
    ("常用哪些", "常用"),
    ("分别是什么", ""),
    ("是什么", ""),
)
LEXICAL_STOP_TOKENS = frozenset(
    {
        "什么",
        "哪些",
        "怎么",
        "如何",
        "论文",
        "本文",
        "这个",
        "这些",
        "其中",
        "主要",
        "进行",
        "研究",
        "please",
        "what",
        "which",
        "how",
        "the",
        "this",
        "that",
        "paper",
    }
)


class XunfeiKnowledgeBaseError(RuntimeError):
    """A safe-to-display ChatDoc error.

    ``message`` must never contain an upstream response body, request headers,
    or a ``requests`` exception string.  The structured fields are safe for
    server-side diagnostics and do not contain credentials.
    """

    def __init__(
        self,
        message: str,
        *,
        code: int | str | None = None,
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
    base_url: str = DEFAULT_BASE_URL
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 600.0

    @classmethod
    def from_env(cls) -> "XunfeiKnowledgeBaseSettings":
        values = {
            "app_id": os.getenv("XFYUN_KB_APP_ID", "").strip(),
            "api_secret": os.getenv("XFYUN_KB_API_SECRET", "").strip(),
            "repo_id": os.getenv("XFYUN_KB_REPO_ID", "").strip(),
        }
        env_names = {
            "app_id": "XFYUN_KB_APP_ID",
            "api_secret": "XFYUN_KB_API_SECRET",
            "repo_id": "XFYUN_KB_REPO_ID",
        }
        missing = [env_names[name] for name, value in values.items() if not value]
        if missing:
            raise XunfeiKnowledgeBaseError(
                "缺少星火知识库配置：" + ", ".join(missing)
            )

        try:
            connect_timeout = float(os.getenv("XFYUN_KB_CONNECT_TIMEOUT", "10"))
            read_timeout = float(os.getenv("XFYUN_KB_READ_TIMEOUT", "600"))
        except (TypeError, ValueError):
            raise XunfeiKnowledgeBaseError(
                "星火知识库超时配置无效，请检查后端环境变量"
            ) from None
        if connect_timeout <= 0 or read_timeout <= 0:
            raise XunfeiKnowledgeBaseError(
                "星火知识库超时配置必须大于 0"
            )

        return cls(
            **values,
            base_url=os.getenv("XFYUN_KB_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            connect_timeout_seconds=connect_timeout,
            read_timeout_seconds=read_timeout,
        )


@dataclass
class XunfeiKnowledgeAnswer:
    content: str = ""
    reasoning_content: str = ""
    sid: str | None = None
    reference_frames: list[dict[str, Any]] = field(default_factory=list)


def is_xunfei_knowledge_base_configured() -> bool:
    return all(
        os.getenv(name, "").strip()
        for name in ("XFYUN_KB_APP_ID", "XFYUN_KB_API_SECRET", "XFYUN_KB_REPO_ID")
    )


def _validated_top_n(top_n: int) -> int:
    if isinstance(top_n, bool) or not isinstance(top_n, int) or not 1 <= top_n <= 20:
        raise ValueError("top_n 必须是 [1, 20] 范围内的整数")
    return top_n


def _validated_filter_policy(policy: str) -> str:
    normalized = str(policy or "").strip().upper()
    if normalized not in RETRIEVAL_FILTER_POLICIES:
        raise ValueError(
            "retrieval_filter_policy 必须是 STRICT、REGULAR、LENIENT 或 OFF"
        )
    return normalized


def _safe_env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        raise XunfeiKnowledgeBaseError(
            f"星火知识库配置 {name} 必须是整数"
        ) from None


def _safe_env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise XunfeiKnowledgeBaseError(
        f"星火知识库配置 {name} 必须是 true 或 false"
    )


def _normalized_query_text(message: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(message or "")).split()).strip()


def _rewritten_keyword_query(message: str) -> str:
    rewritten = _normalized_query_text(message)
    for phrase in QUERY_REWRITE_NOISE:
        rewritten = rewritten.replace(phrase, " ")
    for phrase, replacement in QUERY_REWRITE_PHRASES:
        rewritten = rewritten.replace(phrase, f" {replacement} ")
    rewritten = re.sub(r"[?？!！,，。；;：:\n\r\t]+", " ", rewritten)
    rewritten = re.sub(r"\s+", " ", rewritten).strip()
    return rewritten


def build_retrieval_queries(
    message: str,
    *,
    max_queries: int | None = None,
) -> list[str]:
    """Build a bounded, deterministic query plan without another model call."""

    original = _normalized_query_text(message)
    if not original:
        raise ValueError("message 不能为空")
    if not _safe_env_bool("XFYUN_KB_QUERY_REWRITE_ENABLED", True):
        return [original]

    resolved_limit = (
        max_queries
        if max_queries is not None
        else _safe_env_int("XFYUN_KB_MAX_QUERY_VARIANTS", 2)
    )
    if isinstance(resolved_limit, bool) or not 1 <= resolved_limit <= 2:
        raise XunfeiKnowledgeBaseError(
            "星火知识库配置 XFYUN_KB_MAX_QUERY_VARIANTS 必须是 1 或 2"
        )

    queries = [original]
    rewritten = _rewritten_keyword_query(original)
    if rewritten and rewritten.casefold() != original.casefold():
        queries.append(rewritten)
    return queries[:resolved_limit]


def _lexical_tokens(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    tokens: set[str] = set()
    for word in re.findall(r"[a-z0-9][a-z0-9_.+-]*", normalized):
        if len(word) > 1 and word not in LEXICAL_STOP_TOKENS:
            tokens.add(word)
    for sequence in re.findall(r"[\u4e00-\u9fff]+", normalized):
        if sequence not in LEXICAL_STOP_TOKENS and len(sequence) <= 10:
            tokens.add(sequence)
        for index in range(max(0, len(sequence) - 1)):
            token = sequence[index : index + 2]
            if token not in LEXICAL_STOP_TOKENS:
                tokens.add(token)
    return tokens


def _citation_identity(citation: Mapping[str, Any]) -> str:
    chunk_id = str(citation.get("chunk_id") or "").strip()
    if chunk_id:
        return chunk_id
    return ":".join(
        (
            str(citation.get("document_id") or "unknown"),
            str(citation.get("chunk_index") or "0"),
        )
    )


def rerank_retrieval_candidates(
    query_results: Sequence[tuple[str, Sequence[Mapping[str, Any]]]],
    *,
    top_n: int,
) -> tuple[list[dict[str, Any]], int]:
    """Fuse provider rankings with RRF and a small lexical relevance signal."""

    _validated_top_n(top_n)
    query_tokens = set().union(*(_lexical_tokens(query) for query, _ in query_results))
    candidates: dict[str, dict[str, Any]] = {}
    for query_index, (query, citations) in enumerate(query_results):
        query_weight = 1.0 if query_index == 0 else 0.85
        for rank, citation in enumerate(citations, start=1):
            identity = _citation_identity(citation)
            entry = candidates.setdefault(
                identity,
                {
                    "citation": dict(citation),
                    "rrf_score": 0.0,
                    "matched_queries": [],
                },
            )
            entry["rrf_score"] += query_weight / (60.0 + rank)
            if query not in entry["matched_queries"]:
                entry["matched_queries"].append(query)

    ranked: list[dict[str, Any]] = []
    for entry in candidates.values():
        citation = entry["citation"]
        evidence_tokens = _lexical_tokens(
            f"{citation.get('title') or ''} {citation.get('excerpt') or ''}"
        )
        overlap = len(query_tokens & evidence_tokens)
        lexical_score = (
            overlap / math.sqrt(max(1, len(query_tokens) * len(evidence_tokens)))
            if query_tokens and evidence_tokens
            else 0.0
        )
        rerank_score = float(entry["rrf_score"]) + lexical_score * 0.03
        ranked.append(
            {
                **citation,
                "matched_queries": entry["matched_queries"],
                "rerank_score": round(rerank_score, 8),
            }
        )

    ranked.sort(
        key=lambda citation: (
            float(citation.get("rerank_score") or 0.0),
            float(citation.get("score") or 0.0),
        ),
        reverse=True,
    )
    selected = ranked[:top_n]
    for index, citation in enumerate(selected, start=1):
        citation["index"] = index
    return selected, len(ranked)


def _env_filter_policy() -> str:
    try:
        return _validated_filter_policy(
            os.getenv("XFYUN_KB_RETRIEVAL_FILTER_POLICY", "REGULAR")
        )
    except ValueError:
        raise XunfeiKnowledgeBaseError(
            "星火知识库配置 XFYUN_KB_RETRIEVAL_FILTER_POLICY 无效"
        ) from None


def _env_temperature() -> float:
    try:
        temperature = float(os.getenv("XFYUN_KB_TEMPERATURE", "0.2"))
    except (TypeError, ValueError):
        raise XunfeiKnowledgeBaseError(
            "星火知识库配置 XFYUN_KB_TEMPERATURE 必须是数字"
        ) from None
    if not 0 <= temperature <= 1:
        raise XunfeiKnowledgeBaseError(
            "星火知识库配置 XFYUN_KB_TEMPERATURE 必须在 [0, 1] 范围内"
        )
    return temperature


class XunfeiKnowledgeBaseClient:
    def __init__(
        self,
        settings: XunfeiKnowledgeBaseSettings,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self._session = session or requests.Session()
        self._file_names: dict[str, str] = {}

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

    @property
    def _timeout(self) -> tuple[float, float]:
        return (
            self.settings.connect_timeout_seconds,
            self.settings.read_timeout_seconds,
        )

    def _post_json(
        self,
        path: str,
        body: Mapping[str, Any],
        *,
        operation: str,
    ) -> dict[str, Any]:
        headers = {
            **self.auth_headers(),
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        }
        return self._post(
            path,
            operation=operation,
            headers=headers,
            json=dict(body),
        )

    def _post_form(
        self,
        path: str,
        fields: Mapping[str, str],
        *,
        operation: str,
    ) -> dict[str, Any]:
        # ChatDoc documents this endpoint as form-data.  Passing a tuple with a
        # null filename makes requests emit a normal multipart text field.
        files = {name: (None, value) for name, value in fields.items()}
        headers = {**self.auth_headers(), "Accept": "application/json"}
        return self._post(
            path,
            operation=operation,
            headers=headers,
            files=files,
        )

    def upload_file(
        self,
        file_name: str,
        content: bytes,
        *,
        mime_type: str = "application/pdf",
    ) -> dict[str, Any]:
        safe_name = Path(file_name).name
        if not safe_name.lower().endswith(".pdf"):
            raise ValueError("星火知识库当前只接收 PDF 论文")
        if not content:
            raise ValueError("上传到星火知识库的文件不能为空")
        if len(content) > MAX_FILE_BYTES:
            raise ValueError("星火知识库单个 PDF 不能超过 20MB")

        multipart = [
            ("file", (safe_name, content, mime_type)),
            ("repoIds", (None, self.settings.repo_id)),
            ("parseType", (None, "AUTO")),
            ("stepByStep", (None, "false")),
            ("needSummary", (None, "false")),
        ]
        return self._post(
            "/openapi/v1/file/upload",
            operation="文件上传",
            headers={**self.auth_headers(), "Accept": "application/json"},
            files=multipart,
        )

    def file_status(self, file_ids: Sequence[str]) -> list[dict[str, Any]]:
        ids = _validated_file_ids(file_ids)
        payload = self._post_form(
            "/openapi/v1/file/status",
            {"fileIds": ",".join(ids)},
            operation="文件状态查询",
        )
        items = _payload_items(payload)
        data = payload.get("data")
        if not items and isinstance(data, Mapping):
            items = [dict(data)]
        return items

    def delete_files(self, file_ids: Sequence[str]) -> None:
        ids = _validated_file_ids(file_ids)
        self._post_form(
            "/openapi/v1/file/del",
            {"fileIds": ",".join(ids)},
            operation="文件删除",
        )

    def _post(
        self,
        path: str,
        *,
        operation: str,
        headers: Mapping[str, str],
        **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            response = self._session.post(
                f"{self.settings.base_url}{path}",
                headers=dict(headers),
                timeout=self._timeout,
                **kwargs,
            )
        except requests.Timeout:
            raise XunfeiKnowledgeBaseError(
                f"星火知识库{operation}超时，请稍后重试"
            ) from None
        except requests.RequestException:
            # requests exception messages can contain a URL, query string, or
            # echoed request data, so they must not cross this boundary.
            raise XunfeiKnowledgeBaseError(
                f"星火知识库{operation}暂时不可用，请稍后重试"
            ) from None

        try:
            if not 200 <= response.status_code < 300:
                raise self._response_error(response, operation=operation)
            try:
                payload = response.json()
            except (TypeError, ValueError):
                raise XunfeiKnowledgeBaseError(
                    f"星火知识库{operation}返回了无法解析的数据",
                    http_status=response.status_code,
                ) from None
            if not isinstance(payload, dict):
                raise XunfeiKnowledgeBaseError(
                    f"星火知识库{operation}返回了无效数据",
                    http_status=response.status_code,
                )
            code = payload.get("code", 0)
            if code not in (0, "0", None):
                raise self._payload_error(
                    payload,
                    operation=operation,
                    http_status=response.status_code,
                )
            return payload
        finally:
            response.close()

    @staticmethod
    def _payload_error(
        payload: Mapping[str, Any],
        *,
        operation: str,
        http_status: int | None = None,
    ) -> XunfeiKnowledgeBaseError:
        code = payload.get("code")
        code_suffix = f"（错误码 {code}）" if code is not None else ""
        return XunfeiKnowledgeBaseError(
            f"星火知识库{operation}失败{code_suffix}",
            code=code,
            sid=str(payload["sid"]) if payload.get("sid") is not None else None,
            http_status=http_status,
        )

    @staticmethod
    def _response_error(
        response: requests.Response,
        *,
        operation: str = "请求",
    ) -> XunfeiKnowledgeBaseError:
        try:
            payload = response.json()
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        code = payload.get("code")
        code_suffix = f"，错误码 {code}" if code is not None else ""
        return XunfeiKnowledgeBaseError(
            f"星火知识库{operation}失败（HTTP {response.status_code}{code_suffix}）",
            code=code,
            sid=str(payload["sid"]) if payload.get("sid") is not None else None,
            http_status=response.status_code,
        )

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
        _validated_top_n(top_n)
        policy = _validated_filter_policy(retrieval_filter_policy)
        if not 0 <= temperature <= 1:
            raise ValueError("temperature 必须在 [0, 1] 范围内")
        return {
            "repoIds": [self.settings.repo_id],
            "topN": top_n,
            "thinkingOutput": thinking_output,
            "messages": [dict(message) for message in messages],
            "chatExtends": {
                "retrievalFilterPolicy": policy,
                "wikiPromptTpl": (
                    "仅根据知识库内容回答；资料不足时明确说明，不得编造来源。"
                ),
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
                timeout=self._timeout,
                stream=True,
            )
        except requests.Timeout:
            raise XunfeiKnowledgeBaseError(
                "星火知识库问答超时，请稍后重试"
            ) from None
        except requests.RequestException:
            raise XunfeiKnowledgeBaseError(
                "星火知识库问答暂时不可用，请稍后重试"
            ) from None

        try:
            if not 200 <= response.status_code < 300:
                raise self._response_error(response, operation="问答")
            response.encoding = "utf-8"
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                try:
                    line = (
                        raw_line.decode("utf-8")
                        if isinstance(raw_line, bytes)
                        else raw_line
                    ).strip()
                except (UnicodeDecodeError, AttributeError):
                    raise XunfeiKnowledgeBaseError(
                        "星火知识库问答返回了无法解析的数据帧"
                    ) from None
                if not line or line.startswith(":") or line.startswith("event:"):
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if not line or line == "[DONE]":
                    continue
                try:
                    frame = json.loads(line)
                except (TypeError, json.JSONDecodeError):
                    raise XunfeiKnowledgeBaseError(
                        "星火知识库问答返回了无法解析的数据帧"
                    ) from None
                if not isinstance(frame, dict):
                    raise XunfeiKnowledgeBaseError(
                        "星火知识库问答返回了无效数据帧"
                    )
                if frame.get("code", 0) not in (0, "0", None):
                    raise self._payload_error(
                        frame,
                        operation="问答",
                        http_status=response.status_code,
                    )
                yield frame
        finally:
            response.close()

    def chat(self, request_body: Mapping[str, Any]) -> XunfeiKnowledgeAnswer:
        result = XunfeiKnowledgeAnswer()
        for frame in self.iter_chat(request_body):
            result.sid = str(frame["sid"]) if frame.get("sid") else result.sid
            if frame.get("status") == 99:
                result.reference_frames.append(frame)
                continue
            result.content += str(frame.get("content") or "")
            result.reasoning_content += str(frame.get("reasoning_content") or "")
        result.content = result.content.strip()
        result.reasoning_content = result.reasoning_content.strip()
        if not result.content:
            raise XunfeiKnowledgeBaseError(
                "星火知识库没有返回回答正文",
                sid=result.sid,
            )
        return result

    def build_vector_search_request(
        self,
        message: str,
        *,
        top_n: int = 6,
        retrieval_filter_policy: str = "REGULAR",
        file_ids: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        content = str(message or "").strip()
        if not content:
            raise ValueError("message 不能为空")
        _validated_top_n(top_n)
        policy = _validated_filter_policy(retrieval_filter_policy)
        request = {
            "topN": top_n,
            "esTopN": top_n,
            "content": content,
            "embedding": True,
            "es": True,
            "reRank": True,
            "chatExtends": {"retrievalFilterPolicy": policy},
        }
        if file_ids is not None:
            request["fileIds"] = _validated_file_ids(file_ids)
        else:
            request["repoIds"] = [self.settings.repo_id]
        return request

    def vector_search(
        self,
        message: str,
        top_n: int = 6,
        *,
        retrieval_filter_policy: str = "REGULAR",
        file_ids: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        request_body = self.build_vector_search_request(
            message,
            top_n=top_n,
            retrieval_filter_policy=retrieval_filter_policy,
            file_ids=file_ids,
        )
        payload = self._post_json(
            "/openapi/v1/vector/search",
            request_body,
            operation="检索",
        )
        hits = _payload_items(payload)
        return _normalize_vector_citations(hits, file_names=self._file_names)

    def repo_info(self) -> dict[str, Any]:
        payload = self._post_form(
            "/openapi/v1/repo/info",
            {"repoId": self.settings.repo_id},
            operation="知识库详情查询",
        )
        data = payload.get("data")
        if isinstance(data, list):
            data = next((item for item in data if isinstance(item, dict)), None)
        if not isinstance(data, dict):
            raise XunfeiKnowledgeBaseError(
                "星火知识库详情查询返回了无效数据",
                sid=str(payload["sid"]) if payload.get("sid") else None,
            )
        return dict(data)

    def repo_files_page(
        self,
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ValueError("page 必须是大于 0 的整数")
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= 100
        ):
            raise ValueError("page_size 必须是 [1, 100] 范围内的整数")
        payload = self._post_json(
            "/openapi/v1/repo/file/list",
            {
                "repoId": self.settings.repo_id,
                "currentPage": page,
                "pageSize": page_size,
            },
            operation="知识库文件查询",
        )
        files = _payload_items(payload)
        for item in files:
            file_id = str(item.get("fileId") or "").strip()
            file_name = str(item.get("fileName") or "").strip()
            if file_id and file_name:
                self._file_names[file_id] = file_name
        return {
            "files": files,
            "total": _payload_total(payload),
            "page": page,
            "page_size": page_size,
            "sid": str(payload["sid"]) if payload.get("sid") else None,
        }

    def repo_files(self, page: int = 1, page_size: int = 100) -> list[dict[str, Any]]:
        """Return one repository file page and cache its file-name mapping."""

        return self.repo_files_page(page=page, page_size=page_size)["files"]


def _payload_items(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [dict(item) for item in data if isinstance(item, Mapping)]
    if isinstance(data, Mapping):
        for key in ("records", "items", "list", "rows", "content"):
            items = data.get(key)
            if isinstance(items, list):
                return [dict(item) for item in items if isinstance(item, Mapping)]
    return []


def _validated_file_ids(file_ids: Sequence[str]) -> list[str]:
    values = [str(file_id).strip() for file_id in file_ids if str(file_id).strip()]
    if not values:
        raise ValueError("file_ids 不能为空")
    if len(values) > 20:
        raise ValueError("file_ids 一次不能超过 20 个")
    return values


def _payload_total(payload: Mapping[str, Any]) -> int | None:
    candidates: list[Any] = []
    data = payload.get("data")
    if isinstance(data, Mapping):
        candidates.extend(
            data.get(key) for key in ("total", "totalCount", "count", "totalElements")
        )
    candidates.extend(
        payload.get(key) for key in ("total", "totalCount", "count", "totalElements")
    )
    for candidate in candidates:
        if isinstance(candidate, bool) or candidate is None:
            continue
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return value
    return None


def _normalize_vector_citations(
    hits: Sequence[Mapping[str, Any]],
    *,
    file_names: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    names = file_names or {}
    citations: list[dict[str, Any]] = []
    for citation_index, hit in enumerate(hits, start=1):
        file_id = str(hit.get("fileId") or "").strip()
        chunk_index = hit.get("index")
        returned_file_name = str(hit.get("fileName") or "").strip()
        file_name = names.get(file_id) or returned_file_name or None
        document_id = file_id or f"xunfei-result-{citation_index}"
        title = file_name or file_id or document_id
        chunk_suffix = chunk_index if chunk_index is not None else citation_index - 1
        citations.append(
            {
                "index": citation_index,
                "document_id": document_id,
                "chunk_id": f"{document_id}:{chunk_suffix}",
                "title": title,
                "chunk_index": chunk_index,
                "source_type": PROVIDER_NAME,
                "source_url": None,
                "file_name": file_name,
                "score": hit.get("score"),
                # Preserve the exact retrieved text.  Truncation belongs at a
                # model/UI boundary, not in the source-of-truth citation.
                "excerpt": str(hit.get("content") or ""),
            }
        )
    return citations


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
                        "source_type": PROVIDER_NAME,
                        "source_url": None,
                        "file_name": None,
                        "score": None,
                        "excerpt": "星火知识库返回的引用片段",
                    }
                )
    return citations


def _collect_repo_files(
    client: XunfeiKnowledgeBaseClient,
    *,
    page_size: int = 100,
    max_pages: int = 100,
) -> tuple[list[dict[str, Any]], int | None]:
    """Collect repository files for exact status counts with a bounded loop."""

    collected: list[dict[str, Any]] = []
    seen_page_signatures: set[tuple[str, ...]] = set()
    total: int | None = None
    for page in range(1, max_pages + 1):
        result = client.repo_files_page(page=page, page_size=page_size)
        files = result["files"]
        if total is None:
            total = result.get("total")
        if not files:
            break
        signature = tuple(str(item.get("fileId") or "") for item in files)
        if signature in seen_page_signatures:
            break
        seen_page_signatures.add(signature)
        collected.extend(files)
        if total is not None and len(collected) >= total:
            break
        if len(files) < page_size:
            break
    return collected, total


def get_xunfei_knowledge_status() -> dict[str, Any]:
    """Return repository readiness and document-vectorization counts.

    Missing configuration is a normal not-ready state.  Once configured, an
    upstream failure is raised as ``XunfeiKnowledgeBaseError`` so the API route
    can translate it to HTTP 502 instead of reporting a false healthy state.
    """

    configured = is_xunfei_knowledge_base_configured()
    repository_id = os.getenv("XFYUN_KB_REPO_ID", "").strip() or None
    status: dict[str, Any] = {
        "provider": PROVIDER_NAME,
        "configured": configured,
        "ready": False,
        "repository_configured": bool(repository_id),
        "repository_id": repository_id,
        "repository_name": None,
        "document_count": 0,
        "vectored_count": 0,
        "files": [],
    }
    if not configured:
        return status

    client = XunfeiKnowledgeBaseClient.from_env()
    info = client.repo_info()
    files, total = _collect_repo_files(client)
    status.update(
        {
            "ready": True,
            "repository_id": str(info.get("repoId") or repository_id),
            "repository_name": str(
                info.get("repoName") or repository_id or "星火知识库"
            ),
            "document_count": total if total is not None else len(files),
            "vectored_count": sum(
                1
                for item in files
                if str(item.get("fileStatus") or "").strip().lower() == "vectored"
            ),
            # Expose a useful preview without allowing an unexpectedly large
            # repository to inflate every status response.
            "files": files[:100],
        }
    )
    return status


def search_xunfei_knowledge_base(
    message: str,
    *,
    top_n: int | None = None,
    file_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Retrieve and locally rerank ChatDoc evidence for legacy callers."""

    return retrieve_xunfei_knowledge_base(
        message,
        top_n=top_n,
        file_ids=file_ids,
    )["citations"]


def retrieve_xunfei_knowledge_base(
    message: str,
    *,
    top_n: int | None = None,
    file_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Run bounded multi-query retrieval and return evidence plus diagnostics."""

    client = XunfeiKnowledgeBaseClient.from_env()
    resolved_top_n = top_n if top_n is not None else _safe_env_int("XFYUN_KB_TOP_N", 6)
    _validated_top_n(resolved_top_n)
    policy = _env_filter_policy()
    queries = build_retrieval_queries(message)
    candidate_top_n = min(20, max(resolved_top_n, resolved_top_n * 2))

    # File names are metadata only.  If listing is temporarily unavailable,
    # retrieval still proceeds and citations fall back to the ChatDoc file ID.
    try:
        client.repo_files(page=1, page_size=100)
    except XunfeiKnowledgeBaseError:
        pass
    query_results: list[tuple[str, list[dict[str, Any]]]] = []
    degraded = False
    for query_index, query in enumerate(queries):
        try:
            citations = client.vector_search(
                query,
                candidate_top_n,
                retrieval_filter_policy=policy,
                file_ids=file_ids,
            )
        except XunfeiKnowledgeBaseError:
            if query_index == 0:
                raise
            degraded = True
            continue
        query_results.append((query, citations))

    citations, candidate_count = rerank_retrieval_candidates(
        query_results,
        top_n=resolved_top_n,
    )
    return {
        "query": queries[0],
        "retrieval_queries": [query for query, _ in query_results],
        "citations": citations,
        "candidate_count": candidate_count,
        "rerank_mode": "rrf-lexical-v1",
        "degraded": degraded,
    }


def upload_xunfei_knowledge_file(
    file_name: str,
    content: bytes,
    *,
    mime_type: str = "application/pdf",
) -> dict[str, Any]:
    client = XunfeiKnowledgeBaseClient.from_env()
    payload = client.upload_file(file_name, content, mime_type=mime_type)
    data = payload.get("data")
    if isinstance(data, Mapping):
        file_id = str(data.get("fileId") or data.get("file_id") or "").strip()
    else:
        file_id = str(data or "").strip()
    if not file_id:
        raise XunfeiKnowledgeBaseError("星火知识库文件上传未返回 fileId")
    return {
        "file_id": file_id,
        "sid": str(payload.get("sid") or "").strip() or None,
        "status": "uploaded",
        "repository_id": client.settings.repo_id,
    }


def get_xunfei_knowledge_file_status(file_id: str) -> str:
    client = XunfeiKnowledgeBaseClient.from_env()
    items = client.file_status([file_id])
    item = next(
        (
            entry
            for entry in items
            if str(entry.get("fileId") or entry.get("file_id") or "").strip()
            == file_id.strip()
        ),
        items[0] if items else None,
    )
    if not isinstance(item, Mapping):
        raise XunfeiKnowledgeBaseError("星火知识库未返回文件状态")
    status = str(item.get("fileStatus") or item.get("status") or "").strip().lower()
    if not status:
        raise XunfeiKnowledgeBaseError("星火知识库返回了无效文件状态")
    return status


def delete_xunfei_knowledge_file(file_id: str) -> None:
    XunfeiKnowledgeBaseClient.from_env().delete_files([file_id])


def ask_xunfei_knowledge_base(
    message: str,
    *,
    top_n: int | None = None,
    thinking_output: bool = False,
) -> dict[str, Any]:
    """Keep the existing ChatDoc SSE question-answering integration."""

    client = XunfeiKnowledgeBaseClient.from_env()
    request = client.build_chat_request(
        [{"role": "user", "content": message}],
        top_n=top_n if top_n is not None else _safe_env_int("XFYUN_KB_TOP_N", 6),
        thinking_output=thinking_output,
        retrieval_filter_policy=_env_filter_policy(),
        temperature=_env_temperature(),
    )
    result = client.chat(request)
    return {
        "reply": result.content,
        "reasoning": result.reasoning_content,
        "citations": _parse_file_references(result.reference_frames),
        "sid": result.sid,
        "reference_frames": result.reference_frames,
    }

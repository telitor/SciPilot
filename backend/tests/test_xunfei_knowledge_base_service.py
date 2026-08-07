import base64
import hashlib
import hmac
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import requests


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import xunfei_knowledge_base_service as service


class _FakeResponse:
    def __init__(self, *, lines=None, payload=None, status_code=200, json_error=None):
        self._lines = lines or []
        self._payload = {"code": 0} if payload is None else payload
        self._json_error = json_error
        self.status_code = status_code
        self.encoding = None
        self.closed = False

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload

    def close(self):
        self.closed = True


class _QueueSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    @property
    def last_call(self):
        return self.calls[-1] if self.calls else None

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected HTTP call")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class XunfeiKnowledgeBaseServiceTests(unittest.TestCase):
    def setUp(self):
        self.settings = service.XunfeiKnowledgeBaseSettings(
            app_id="app-test",
            api_secret="secret-test",
            repo_id="repo-test",
        )

    @staticmethod
    def _configured_environment(**overrides):
        environment = {
            "XFYUN_KB_APP_ID": "app-test",
            "XFYUN_KB_API_SECRET": "secret-test",
            "XFYUN_KB_REPO_ID": "repo-test",
        }
        environment.update(overrides)
        return environment

    def test_signature_and_auth_headers_match_documented_algorithm(self):
        timestamp = 1710000000
        auth = hashlib.md5(f"app-test{timestamp}".encode()).hexdigest()
        expected = base64.b64encode(
            hmac.new(b"secret-test", auth.encode(), hashlib.sha1).digest()
        ).decode()
        client = service.XunfeiKnowledgeBaseClient(self.settings)

        headers = client.auth_headers(timestamp)

        self.assertEqual(headers["appId"], "app-test")
        self.assertEqual(headers["timeStamp"], str(timestamp))
        self.assertEqual(headers["signature"], expected)
        self.assertNotIn("secret-test", str(headers))

    def test_chat_request_uses_server_repository(self):
        client = service.XunfeiKnowledgeBaseClient(self.settings)
        payload = client.build_chat_request(
            [{"role": "user", "content": "如何管理质量需求？"}], top_n=4
        )

        self.assertEqual(payload["repoIds"], ["repo-test"])
        self.assertEqual(payload["topN"], 4)
        self.assertEqual(
            payload["chatExtends"]["retrievalFilterPolicy"], "REGULAR"
        )

    def test_chat_separates_answer_and_reference_frames(self):
        lines = [
            'data: {"code":0,"sid":"sid-1","status":0,"content":"答案"}',
            'data: {"code":0,"sid":"sid-1","status":2,"content":"正文"}',
            "data: "
            + json.dumps(
                {
                    "code": 0,
                    "sid": "sid-1",
                    "status": 99,
                    "fileRefer": json.dumps({"file-1": [2, 4]}),
                }
            ),
        ]
        response = _FakeResponse(lines=lines)
        session = _QueueSession(response)
        client = service.XunfeiKnowledgeBaseClient(self.settings, session=session)

        result = client.chat({"repoIds": ["repo-test"], "messages": []})

        self.assertEqual(result.content, "答案正文")
        self.assertEqual(result.sid, "sid-1")
        self.assertEqual(len(result.reference_frames), 1)
        citations = service._parse_file_references(result.reference_frames)
        self.assertEqual(len(citations), 2)
        self.assertEqual(citations[0]["document_id"], "file-1")
        self.assertEqual(citations[0]["source_type"], "xunfei-chatdoc")
        self.assertTrue(response.closed)
        self.assertNotIn("secret-test", str(session.last_call))

    def test_vector_search_sends_hybrid_rerank_request_and_normalizes_hits(self):
        response = _FakeResponse(
            payload={
                "code": 0,
                "sid": "sid-vector",
                "data": [
                    {
                        "content": "原始检索片段，不应截断。",
                        "score": 0.91,
                        "fileId": "file-1",
                        "index": 7,
                    },
                    {
                        "content": "第二个片段",
                        "score": 0.62,
                        "fileId": "file-2",
                        "index": 2,
                        "fileName": "paper-two.pdf",
                    },
                ],
            }
        )
        session = _QueueSession(response)
        client = service.XunfeiKnowledgeBaseClient(self.settings, session=session)

        citations = client.vector_search("  什么是 SciPilot？  ", 4)

        url, call = session.last_call
        self.assertEqual(url, "https://chatdoc.xfyun.cn/openapi/v1/vector/search")
        self.assertEqual(
            call["json"],
            {
                "repoIds": ["repo-test"],
                "topN": 4,
                "esTopN": 4,
                "content": "什么是 SciPilot？",
                "embedding": True,
                "es": True,
                "reRank": True,
                "chatExtends": {"retrievalFilterPolicy": "REGULAR"},
            },
        )
        self.assertEqual(call["headers"]["appId"], "app-test")
        self.assertIn("signature", call["headers"])
        self.assertEqual(citations[0]["index"], 1)
        self.assertEqual(citations[0]["document_id"], "file-1")
        self.assertEqual(citations[0]["title"], "file-1")
        self.assertEqual(citations[0]["chunk_index"], 7)
        self.assertEqual(citations[0]["score"], 0.91)
        self.assertEqual(citations[0]["excerpt"], "原始检索片段，不应截断。")
        self.assertEqual(citations[1]["title"], "paper-two.pdf")
        self.assertTrue(response.closed)

    def test_repo_files_supplies_file_name_mapping_for_vector_citations(self):
        files_response = _FakeResponse(
            payload={
                "code": 0,
                "data": [
                    {
                        "fileId": "file-1",
                        "fileName": "mapped-paper.pdf",
                        "fileStatus": "vectored",
                    }
                ],
            }
        )
        vector_response = _FakeResponse(
            payload={
                "code": 0,
                "data": [
                    {
                        "fileId": "file-1",
                        "index": 0,
                        "score": 0.8,
                        "content": "evidence",
                    }
                ],
            }
        )
        session = _QueueSession(files_response, vector_response)
        client = service.XunfeiKnowledgeBaseClient(self.settings, session=session)

        files = client.repo_files(page=1, page_size=20)
        citations = client.vector_search("question", 3)

        self.assertEqual(files[0]["fileName"], "mapped-paper.pdf")
        self.assertEqual(citations[0]["title"], "mapped-paper.pdf")
        self.assertEqual(citations[0]["file_name"], "mapped-paper.pdf")
        files_url, files_call = session.calls[0]
        self.assertEqual(
            files_url, "https://chatdoc.xfyun.cn/openapi/v1/repo/file/list"
        )
        self.assertEqual(files_call["json"]["currentPage"], 1)
        self.assertEqual(files_call["json"]["pageSize"], 20)

    def test_repo_info_accepts_documented_list_shaped_example(self):
        response = _FakeResponse(
            payload={
                "code": 0,
                "data": [{"repoId": "repo-test", "repoName": "论文知识库"}],
            }
        )
        session = _QueueSession(response)
        client = service.XunfeiKnowledgeBaseClient(self.settings, session=session)

        info = client.repo_info()

        self.assertEqual(info["repoName"], "论文知识库")
        url, call = session.last_call
        self.assertEqual(url, "https://chatdoc.xfyun.cn/openapi/v1/repo/info")
        self.assertEqual(call["files"]["repoId"], (None, "repo-test"))

    def test_status_reports_repository_and_vectorized_document_counts(self):
        info_response = _FakeResponse(
            payload={
                "code": 0,
                "data": {"repoId": "repo-test", "repoName": "SciPilot Papers"},
            }
        )
        files_response = _FakeResponse(
            payload={
                "code": 0,
                "data": [
                    {"fileId": "a", "fileName": "a.pdf", "fileStatus": "vectored"},
                    {"fileId": "b", "fileName": "b.pdf", "fileStatus": "vectoring"},
                    {"fileId": "c", "fileName": "c.pdf", "fileStatus": "VECTORED"},
                ],
            }
        )
        client = service.XunfeiKnowledgeBaseClient(
            self.settings, session=_QueueSession(info_response, files_response)
        )
        with patch.dict(os.environ, self._configured_environment(), clear=True), patch.object(
            service.XunfeiKnowledgeBaseClient, "from_env", return_value=client
        ):
            status = service.get_xunfei_knowledge_status()

        self.assertTrue(status["configured"])
        self.assertTrue(status["ready"])
        self.assertEqual(status["repository_name"], "SciPilot Papers")
        self.assertEqual(status["document_count"], 3)
        self.assertEqual(status["vectored_count"], 2)
        self.assertEqual(len(status["files"]), 3)

    def test_unconfigured_status_is_not_ready_and_does_not_call_upstream(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
            service.XunfeiKnowledgeBaseClient,
            "from_env",
            side_effect=AssertionError("must not be called"),
        ):
            status = service.get_xunfei_knowledge_status()

        self.assertFalse(status["configured"])
        self.assertFalse(status["ready"])
        self.assertEqual(status["document_count"], 0)

    def test_public_search_returns_citations_with_repository_file_names(self):
        files_response = _FakeResponse(
            payload={
                "code": 0,
                "data": [{"fileId": "f-1", "fileName": "source.pdf"}],
            }
        )
        vector_response = _FakeResponse(
            payload={
                "code": 0,
                "data": [
                    {
                        "fileId": "f-1",
                        "index": 4,
                        "content": "source text",
                        "score": 0.75,
                    }
                ],
            }
        )
        client = service.XunfeiKnowledgeBaseClient(
            self.settings, session=_QueueSession(files_response, vector_response)
        )
        with patch.dict(os.environ, self._configured_environment(), clear=True), patch.object(
            service.XunfeiKnowledgeBaseClient, "from_env", return_value=client
        ):
            citations = service.search_xunfei_knowledge_base("research question", top_n=5)

        self.assertIsInstance(citations, list)
        self.assertEqual(citations[0]["title"], "source.pdf")
        self.assertEqual(citations[0]["excerpt"], "source text")

    def test_missing_environment_reports_exact_variables(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(service.XunfeiKnowledgeBaseError) as error:
                service.XunfeiKnowledgeBaseSettings.from_env()

        message = str(error.exception)
        self.assertIn("XFYUN_KB_APP_ID", message)
        self.assertIn("XFYUN_KB_API_SECRET", message)
        self.assertIn("XFYUN_KB_REPO_ID", message)

    def test_http_and_provider_errors_do_not_leak_upstream_secrets(self):
        leaked_secret = "upstream-echoed-secret"
        http_response = _FakeResponse(
            status_code=401,
            payload={
                "code": 10013,
                "sid": "sid-safe",
                "desc": f"bad credential {leaked_secret} secret-test",
            },
        )
        client = service.XunfeiKnowledgeBaseClient(
            self.settings, session=_QueueSession(http_response)
        )

        with self.assertRaises(service.XunfeiKnowledgeBaseError) as caught:
            client.vector_search("question", 3)

        message = str(caught.exception)
        self.assertNotIn(leaked_secret, message)
        self.assertNotIn("secret-test", message)
        self.assertEqual(caught.exception.code, 10013)
        self.assertEqual(caught.exception.sid, "sid-safe")
        self.assertEqual(caught.exception.http_status, 401)

    def test_transport_error_is_sanitized(self):
        leaked_secret = "transport-secret"
        client = service.XunfeiKnowledgeBaseClient(
            self.settings,
            session=_QueueSession(requests.ConnectionError(leaked_secret)),
        )

        with self.assertRaises(service.XunfeiKnowledgeBaseError) as caught:
            client.vector_search("question", 3)

        self.assertNotIn(leaked_secret, str(caught.exception))
        self.assertIn("暂时不可用", str(caught.exception))

    def test_provider_error_frame_is_sanitized(self):
        response = _FakeResponse(
            payload={
                "code": 20001,
                "sid": "sid-provider",
                "desc": "provider-secret should not escape",
            }
        )
        client = service.XunfeiKnowledgeBaseClient(
            self.settings, session=_QueueSession(response)
        )

        with self.assertRaises(service.XunfeiKnowledgeBaseError) as caught:
            client.repo_files()

        self.assertNotIn("provider-secret", str(caught.exception))
        self.assertEqual(caught.exception.code, 20001)
        self.assertEqual(caught.exception.sid, "sid-provider")


if __name__ == "__main__":
    unittest.main()

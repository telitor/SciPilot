import base64
import hashlib
import hmac
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import xunfei_knowledge_base_service as service


class _FakeResponse:
    def __init__(self, *, lines=None, payload=None, status_code=200):
        self._lines = lines or []
        self._payload = payload or {"code": 0}
        self.status_code = status_code
        self.encoding = None
        self.closed = False

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)

    def json(self):
        return self._payload

    def close(self):
        self.closed = True


class _FakeSession:
    def __init__(self, response):
        self.response = response
        self.last_call = None

    def post(self, url, **kwargs):
        self.last_call = (url, kwargs)
        return self.response


class XunfeiKnowledgeBaseServiceTests(unittest.TestCase):
    def setUp(self):
        self.settings = service.XunfeiKnowledgeBaseSettings(
            app_id="app-test",
            api_secret="secret-test",
            repo_id="repo-test",
        )

    def test_signature_matches_documented_algorithm(self):
        timestamp = 1710000000
        auth = hashlib.md5(f"app-test{timestamp}".encode()).hexdigest()
        expected = base64.b64encode(
            hmac.new(b"secret-test", auth.encode(), hashlib.sha1).digest()
        ).decode()
        self.assertEqual(
            service.XunfeiKnowledgeBaseClient.make_signature(
                "app-test", "secret-test", timestamp
            ),
            expected,
        )

    def test_chat_request_uses_server_repository(self):
        client = service.XunfeiKnowledgeBaseClient(self.settings)
        payload = client.build_chat_request(
            [{"role": "user", "content": "如何管理质量需求？"}], top_n=4
        )
        self.assertEqual(payload["repoIds"], ["repo-test"])
        self.assertEqual(payload["topN"], 4)

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
        session = _FakeSession(response)
        client = service.XunfeiKnowledgeBaseClient(
            self.settings, session=session
        )

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

    def test_missing_environment_reports_exact_variables(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(service.XunfeiKnowledgeBaseError) as error:
                service.XunfeiKnowledgeBaseSettings.from_env()
        message = str(error.exception)
        self.assertIn("XFYUN_KB_APP_ID", message)
        self.assertIn("XFYUN_KB_API_SECRET", message)
        self.assertIn("XFYUN_KB_REPO_ID", message)


if __name__ == "__main__":
    unittest.main()

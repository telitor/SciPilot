import base64
import hashlib
import hmac
import json
import unittest

from xfyun_knowledge_base import (
    XfyunKnowledgeBaseClient,
    XfyunKnowledgeBaseSettings,
)


class _FakeResponse:
    def __init__(self, payload=None, lines=None, status_code=200):
        self._payload = payload or {"code": 0}
        self._lines = lines or []
        self.status_code = status_code
        self.encoding = None
        self.closed = False

    def json(self):
        return self._payload

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)

    def close(self):
        self.closed = True


class _FakeSession:
    def __init__(self, response):
        self.response = response
        self.last_call = None

    def request(self, method, url, **kwargs):
        self.last_call = (method, url, kwargs)
        return self.response

    def post(self, url, **kwargs):
        self.last_call = ("POST", url, kwargs)
        return self.response


class XfyunKnowledgeBaseClientTests(unittest.TestCase):
    def setUp(self):
        self.settings = XfyunKnowledgeBaseSettings("app-test", "secret-test")

    def test_signature_matches_documented_algorithm(self):
        timestamp = 1710000000
        auth = hashlib.md5(f"app-test{timestamp}".encode()).hexdigest()
        expected = base64.b64encode(
            hmac.new(b"secret-test", auth.encode(), hashlib.sha1).digest()
        ).decode()
        self.assertEqual(
            XfyunKnowledgeBaseClient.make_signature(
                "app-test", "secret-test", timestamp
            ),
            expected,
        )

    def test_headers_use_documented_names(self):
        client = XfyunKnowledgeBaseClient(self.settings)
        headers = client.auth_headers(1710000000)
        self.assertEqual(headers["appId"], "app-test")
        self.assertEqual(headers["timeStamp"], "1710000000")
        self.assertTrue(headers["signature"])

    def test_build_chat_request_requires_one_source(self):
        client = XfyunKnowledgeBaseClient(self.settings)
        with self.assertRaises(ValueError):
            client.build_chat_request([{"role": "user", "content": "hi"}])
        payload = client.build_chat_request(
            [{"role": "user", "content": "hi"}], repo_ids=["repo-1"]
        )
        self.assertEqual(payload["repoIds"], ["repo-1"])
        self.assertNotIn("fileIds", payload)

    def test_chat_parses_sse_and_keeps_references(self):
        lines = [
            'data: {"code":0,"sid":"sid-1","status":0,"content":"你"}',
            'data: {"code":0,"sid":"sid-1","status":2,"content":"好"}',
            'data: '
            + json.dumps(
                {"code": 0, "sid": "sid-1", "status": 99, "fileRefer": "{}"}
            ),
        ]
        session = _FakeSession(_FakeResponse(lines=lines))
        client = XfyunKnowledgeBaseClient(self.settings, session=session)
        result = client.chat({"repoIds": ["repo-1"], "messages": []})
        self.assertEqual(result.content, "你好")
        self.assertEqual(result.sid, "sid-1")
        self.assertEqual(len(result.references), 1)
        self.assertTrue(session.response.closed)


if __name__ == "__main__":
    unittest.main()

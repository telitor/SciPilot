import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException

from api import routes
from services import agent_knowledge_service as service


class _Result:
    def __init__(self, data):
        self.data = data


class _CollectionQuery:
    def __init__(self, row):
        self.row = row

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return _Result([self.row] if self.row else [])


class _Database:
    def __init__(self, row):
        self.row = row

    def table(self, _name):
        return _CollectionQuery(self.row)


class AgentKnowledgeServiceTests(unittest.TestCase):
    def setUp(self):
        self.agent = {
            "id": "agent-1",
            "name": "代码复现助手",
            "category": "code-reproduction",
            "system_prompt": "只根据证据回答。",
        }
        self.rows = [
            {
                "document_id": "document-1",
                "chunk_id": "chunk-1",
                "document_title": "可复现实验指南",
                "content": "固定依赖版本，并记录随机种子。",
                "score": 0.91,
            }
        ]

    def test_citations_are_bounded_and_ranked(self):
        citations = service.build_citations(self.rows, excerpt_chars=8)
        self.assertEqual(citations[0]["index"], 1)
        self.assertEqual(citations[0]["title"], "可复现实验指南")
        self.assertLessEqual(len(citations[0]["excerpt"]), 8)

    def test_no_evidence_never_calls_a_model(self):
        reply, mode, model = service.grounded_agent_reply(
            agent=self.agent,
            message="如何复现实验？",
            citations=[],
        )
        self.assertEqual(reply, service.NO_EVIDENCE_REPLY)
        self.assertEqual(mode, "no-evidence")
        self.assertIsNone(model)

    def test_missing_provider_returns_extracts_with_citations(self):
        citations = service.build_citations(self.rows)
        with patch.dict(os.environ, {}, clear=True):
            reply, mode, model = service.grounded_agent_reply(
                agent=self.agent,
                message="如何复现实验？",
                citations=citations,
            )
        self.assertIn("[1]", reply)
        self.assertIn("固定依赖版本", reply)
        self.assertEqual(mode, "extractive")
        self.assertIsNone(model)

    def test_invalid_model_citation_falls_back_to_trusted_extract(self):
        citations = service.build_citations(self.rows)
        with (
            patch.dict(os.environ, {"LLM_API_KEY": "configured"}, clear=True),
            patch.object(service, "call_default_llm", return_value="结论见 [99]。"),
        ):
            reply, mode, _model = service.grounded_agent_reply(
                agent=self.agent,
                message="如何复现实验？",
                citations=citations,
            )
        self.assertNotIn("[99]", reply)
        self.assertIn("[1]", reply)
        self.assertEqual(mode, "extractive")

    def test_valid_model_citation_is_kept(self):
        citations = service.build_citations(self.rows)
        with (
            patch.dict(
                os.environ,
                {"LLM_API_KEY": "configured", "LLM_MODEL": "test-model"},
                clear=True,
            ),
            patch.object(
                service,
                "call_default_llm",
                return_value="应固定依赖版本并记录随机种子 [1]。",
            ),
        ):
            reply, mode, model = service.grounded_agent_reply(
                agent=self.agent,
                message="如何复现实验？",
                citations=citations,
            )
        self.assertEqual(reply, "应固定依赖版本并记录随机种子 [1]。")
        self.assertEqual(mode, "model")
        self.assertEqual(model, "test-model")


class KnowledgeAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(id="user-1")

    def _collection(self, **changes):
        row = {
            "id": "collection-1",
            "user_id": "owner-1",
            "is_public": False,
            "metadata": {},
        }
        row.update(changes)
        return row

    def test_public_collection_is_visible_to_another_user(self):
        row = self._collection(is_public=True)
        with patch.object(routes, "database", return_value=_Database(row)):
            result = routes._require_visible_kb_collection(
                "collection-1", "user-1"
            )
        self.assertEqual(result["id"], "collection-1")

    def test_another_users_private_collection_is_hidden(self):
        row = self._collection()
        with (
            patch.object(routes, "database", return_value=_Database(row)),
            self.assertRaises(HTTPException) as error,
        ):
            routes._require_visible_kb_collection("collection-1", "user-1")
        self.assertEqual(error.exception.status_code, 404)

    def test_non_admin_cannot_write_system_collection(self):
        row = self._collection(
            is_public=True,
            metadata={"system_managed": True},
        )
        with (
            patch.object(routes, "database", return_value=_Database(row)),
            patch.object(
                routes,
                "get_or_create_profile",
                return_value={"role": "user"},
            ),
            self.assertRaises(HTTPException) as error,
        ):
            routes._require_writable_kb_collection("collection-1", self.user)
        self.assertEqual(error.exception.status_code, 403)

    def test_admin_can_write_system_collection(self):
        row = self._collection(
            is_public=True,
            metadata={"system_managed": True},
        )
        with (
            patch.object(routes, "database", return_value=_Database(row)),
            patch.object(
                routes,
                "get_or_create_profile",
                return_value={"role": "admin"},
            ),
        ):
            result = routes._require_writable_kb_collection(
                "collection-1", self.user
            )
        self.assertEqual(result["id"], "collection-1")

    def test_owner_can_write_private_collection(self):
        row = self._collection(user_id="user-1")
        with patch.object(routes, "database", return_value=_Database(row)):
            result = routes._require_writable_kb_collection(
                "collection-1", self.user
            )
        self.assertEqual(result["id"], "collection-1")


if __name__ == "__main__":
    unittest.main()

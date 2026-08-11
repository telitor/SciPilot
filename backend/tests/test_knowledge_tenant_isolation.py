import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from api import routes


class KnowledgeTenantIsolationTests(unittest.TestCase):
    def test_empty_allowlist_never_calls_shared_repository_search(self):
        with patch.object(routes, "retrieve_xunfei_knowledge_base") as retrieve:
            result = routes._retrieve_external_knowledge(
                "test query",
                top_n=6,
                file_ids=[],
            )

        retrieve.assert_not_called()
        self.assertEqual(result["citations"], [])
        self.assertEqual(result["rerank_mode"], "user-file-scope-empty")

    def test_retrieval_forwards_only_the_explicit_owned_file_allowlist(self):
        expected = {
            "citations": [],
            "retrieval_queries": ["test query"],
            "candidate_count": 0,
            "rerank_mode": "rrf-lexical-v1",
            "degraded": False,
        }
        with patch.object(
            routes,
            "retrieve_xunfei_knowledge_base",
            return_value=expected,
        ) as retrieve:
            result = routes._retrieve_external_knowledge(
                "test query",
                top_n=6,
                file_ids=["owned-file"],
            )

        self.assertEqual(result, expected)
        retrieve.assert_called_once_with(
            "test query",
            top_n=6,
            file_ids=["owned-file"],
        )

    def test_retrieval_drops_provider_results_outside_the_allowlist(self):
        provider_result = {
            "citations": [
                {"document_id": "owned-file", "excerpt": "owned"},
                {"document_id": "other-file", "excerpt": "private"},
            ],
            "retrieval_queries": ["test query"],
            "candidate_count": 2,
            "rerank_mode": "rrf-lexical-v1",
            "degraded": False,
        }
        with patch.object(
            routes,
            "retrieve_xunfei_knowledge_base",
            return_value=provider_result,
        ):
            result = routes._retrieve_external_knowledge(
                "test query",
                top_n=6,
                file_ids=["owned-file"],
            )

        self.assertEqual(
            [item["document_id"] for item in result["citations"]],
            ["owned-file"],
        )
        self.assertNotIn("private", str(result["citations"]))

    def test_status_never_exposes_another_users_remote_file(self):
        mappings = [
            {
                "paper_id": "paper-1",
                "provider_file_id": "owned-file",
                "file_name": "owned.pdf",
                "status": "vectored",
                "updated_at": "2026-08-11T00:00:00Z",
            }
        ]
        remote_status = {
            "provider": "xunfei-chatdoc",
            "configured": True,
            "ready": True,
            "repository_name": "shared-repo",
            "document_count": 2,
            "vectored_count": 2,
            "files": [
                {"fileId": "owned-file", "fileName": "owned.pdf", "fileStatus": "vectored"},
                {"fileId": "other-file", "fileName": "private-other.pdf", "fileStatus": "vectored"},
            ],
        }
        with (
            patch.object(routes, "_owned_knowledge_mappings", return_value=mappings),
            patch.object(routes, "get_xunfei_knowledge_status", return_value=remote_status),
        ):
            result = routes._public_knowledge_status("user-1")

        self.assertEqual(result["document_count"], 1)
        self.assertEqual(result["vectored_count"], 1)
        self.assertEqual([item["file_id"] for item in result["files"]], ["owned-file"])
        self.assertNotIn("private-other.pdf", str(result))

    def test_knowledge_endpoint_builds_allowlist_from_authenticated_user(self):
        payload = SimpleNamespace(text="test query", top_n=6)
        retrieval = {
            "citations": [],
            "retrieval_queries": [],
            "candidate_count": 0,
            "rerank_mode": "user-file-scope-empty",
            "degraded": False,
        }
        with (
            patch.object(routes, "_owned_vectored_file_ids", return_value=["owned-file"]) as owned,
            patch.object(routes, "_retrieve_external_knowledge", return_value=retrieval) as retrieve,
            patch.object(routes, "record_activity"),
        ):
            result = routes.search_knowledge_base(payload, user=SimpleNamespace(id="user-1"))

        owned.assert_called_once_with("user-1")
        retrieve.assert_called_once_with("test query", top_n=6, file_ids=["owned-file"])
        self.assertEqual(result["citations"], [])


if __name__ == "__main__":
    unittest.main()

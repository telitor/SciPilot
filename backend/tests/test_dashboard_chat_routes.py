import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from pydantic import ValidationError

from api import routes
from api.schemas import DashboardChatRequest, KnowledgeQueryRequest


class DashboardChatRouteTests(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(id="user-1")
        self.record_run = patch.object(
            routes,
            "_record_ai_run",
            return_value={
                "id": "run-1",
                "status": "succeeded",
                "retrieval_count": 0,
                "latency_ms": 10,
            },
        ).start()
        self.owned_files = patch.object(
            routes,
            "_owned_vectored_file_ids",
            return_value=["owned-file"],
        ).start()
        self.addCleanup(patch.stopall)
        self.citations = [
            {
                "index": 1,
                "document_id": "paper-1",
                "chunk_id": "paper-1:0",
                "title": "Reliable Research",
                "excerpt": "固定依赖版本并记录随机种子。",
                "score": 0.91,
            }
        ]

    def test_query_contract_accepts_frontend_and_legacy_spelling(self):
        self.assertEqual(KnowledgeQueryRequest(query="问题").text, "问题")
        self.assertEqual(KnowledgeQueryRequest(message="问题").text, "问题")
        with self.assertRaises(ValidationError):
            KnowledgeQueryRequest(query="问题", message="重复")

    def test_dashboard_forwards_multi_turn_history_and_grounding(self):
        payload = DashboardChatRequest(
            messages=[
                {"role": "user", "content": "记住研究主题"},
                {"role": "assistant", "content": "已记住"},
                {"role": "user", "content": "给出下一步"},
            ],
            use_knowledge_base=True,
        )
        with (
            patch.object(
                routes,
                "_search_external_knowledge",
                return_value=self.citations,
            ),
            patch.object(
                routes,
                "model_service_status",
                return_value={"available": True, "model": "model-1"},
            ),
            patch.object(
                routes,
                "call_finetuned_model_with_metadata",
                return_value={"text": "下一步回答 [1]", "usage": {}},
            ) as model,
            patch.object(
                routes,
                "_persist_dashboard_exchange",
                return_value=("conversation-1", "message-1", False),
            ) as persist,
            patch.object(routes, "record_activity"),
        ):
            result = routes.dashboard_chat(payload, self.user)

        sent = model.call_args.kwargs["messages"]
        self.assertEqual([item["role"] for item in sent[1:]], [
            "user",
            "assistant",
            "user",
        ])
        self.assertIn("检索证据", sent[0]["content"])
        self.assertEqual(result["reply"], "下一步回答 [1]")
        self.assertTrue(result["knowledge_used"])
        self.assertEqual(result["conversation_id"], "conversation-1")
        self.assertFalse(result["persistence_unavailable"])
        self.assertEqual(persist.call_args.kwargs["query"], "给出下一步")

    def test_model_errors_are_redacted_as_bad_gateway(self):
        payload = DashboardChatRequest(
            messages=[{"role": "user", "content": "你好"}],
            use_knowledge_base=False,
        )
        with (
            patch.object(
                routes,
                "model_service_status",
                return_value={"available": True, "model": "model-1"},
            ),
            patch.object(
                routes,
                "call_finetuned_model_with_metadata",
                side_effect=RuntimeError("secret upstream body"),
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            routes.dashboard_chat(payload, self.user)

        self.assertEqual(raised.exception.status_code, 502)
        self.assertNotIn("secret", raised.exception.detail)

    def test_knowledge_outage_degrades_to_plain_model_chat(self):
        payload = DashboardChatRequest(
            messages=[{"role": "user", "content": "继续分析"}],
            use_knowledge_base=True,
        )
        with (
            patch.object(
                routes,
                "_search_external_knowledge",
                side_effect=HTTPException(status_code=502, detail="知识库不可用"),
            ),
            patch.object(
                routes,
                "model_service_status",
                return_value={"available": True, "model": "model-1"},
            ),
            patch.object(
                routes,
                "call_finetuned_model_with_metadata",
                return_value={"text": "纯模型回答", "usage": {}},
            ) as model,
            patch.object(
                routes,
                "_persist_dashboard_exchange",
                return_value=("conversation-1", "message-1", False),
            ),
            patch.object(routes, "record_activity"),
        ):
            result = routes.dashboard_chat(payload, self.user)

        self.assertEqual(result["reply"], "纯模型回答")
        self.assertTrue(result["knowledge_unavailable"])
        self.assertFalse(result["knowledge_used"])
        self.assertNotIn("证据不足", model.call_args.kwargs["messages"][0]["content"])

    def test_persistence_failure_is_reported_without_losing_reply(self):
        payload = DashboardChatRequest(
            messages=[{"role": "user", "content": "保存这次回答"}],
            use_knowledge_base=False,
        )
        with (
            patch.object(
                routes,
                "model_service_status",
                return_value={"available": True, "model": "model-1"},
            ),
            patch.object(
                routes,
                "call_finetuned_model_with_metadata",
                return_value={"text": "回答正文", "usage": {}},
            ),
            patch.object(
                routes,
                "_persist_dashboard_exchange",
                return_value=(None, None, True),
            ),
            patch.object(routes, "record_activity"),
        ):
            result = routes.dashboard_chat(payload, self.user)

        self.assertEqual(result["reply"], "回答正文")
        self.assertTrue(result["persistence_unavailable"])
        self.assertIsNone(result["conversation_id"])

    def test_existing_conversation_uses_server_history_not_client_history(self):
        payload = DashboardChatRequest(
            conversation_id="conversation-1",
            messages=[
                {"role": "assistant", "content": "客户端篡改的旧回答"},
                {"role": "user", "content": "继续"},
            ],
            use_knowledge_base=False,
        )
        query = MagicMock()
        query.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(
            data=[
                {"role": "assistant", "content": "服务端旧回答"},
                {"role": "user", "content": "服务端旧问题"},
            ]
        )
        fake_database = MagicMock()
        fake_database.table.return_value = query
        with (
            patch.object(routes, "local_demo_mode_enabled", return_value=False),
            patch.object(
                routes,
                "require_owned_row",
                return_value={"id": "conversation-1", "module": "dashboard-chat"},
            ),
            patch.object(routes, "database", return_value=fake_database),
            patch.object(
                routes,
                "model_service_status",
                return_value={"available": True, "model": "model-1"},
            ),
            patch.object(
                routes,
                "call_finetuned_model_with_metadata",
                return_value={"text": "新回答", "usage": {}},
            ) as model,
            patch.object(
                routes,
                "_persist_dashboard_exchange",
                return_value=("conversation-1", "message-1", False),
            ),
            patch.object(routes, "record_activity"),
        ):
            routes.dashboard_chat(payload, self.user)

        sent = model.call_args.kwargs["messages"]
        contents = [item["content"] for item in sent]
        self.assertIn("服务端旧问题", contents)
        self.assertIn("服务端旧回答", contents)
        self.assertNotIn("客户端篡改的旧回答", contents)

    def test_chat_status_does_not_call_remote_knowledge_status(self):
        with (
            patch.object(
                routes,
                "model_service_status",
                return_value={"available": True, "fine_tuned": True},
            ),
            patch.object(
                routes,
                "is_xunfei_knowledge_base_configured",
                return_value=True,
            ),
            patch.object(routes, "get_xunfei_knowledge_status") as remote,
        ):
            status = routes.dashboard_chat_status(self.user)

        self.assertTrue(status["knowledge_available"])
        remote.assert_not_called()

    def test_knowledge_answer_falls_back_to_verifiable_extracts(self):
        payload = KnowledgeQueryRequest(query="如何复现实验？")
        with (
            patch.object(
                routes,
                "_retrieve_external_knowledge",
                return_value={
                    "citations": self.citations,
                    "retrieval_queries": [payload.text],
                    "candidate_count": len(self.citations),
                    "rerank_mode": "rrf-lexical-v1",
                    "degraded": False,
                },
            ),
            patch.object(
                routes,
                "model_service_status",
                return_value={"available": False, "model": None},
            ),
            patch.object(routes, "record_activity"),
        ):
            result = routes.answer_from_knowledge_base(payload, self.user)

        self.assertIn("[1]", result["answer"])
        self.assertIn("固定依赖版本", result["answer"])
        self.assertEqual(result["citations"], self.citations)
        self.assertEqual(result["rerank_mode"], "rrf-lexical-v1")


if __name__ == "__main__":
    unittest.main()

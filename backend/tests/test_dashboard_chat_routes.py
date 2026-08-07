import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from pydantic import ValidationError

from api import routes
from api.schemas import DashboardChatRequest, KnowledgeQueryRequest


class DashboardChatRouteTests(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(id="user-1")
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
                "call_finetuned_model",
                return_value="下一步回答 [1]",
            ) as model,
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
                "call_finetuned_model",
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
                "call_finetuned_model",
                return_value="纯模型回答",
            ) as model,
            patch.object(routes, "record_activity"),
        ):
            result = routes.dashboard_chat(payload, self.user)

        self.assertEqual(result["reply"], "纯模型回答")
        self.assertTrue(result["knowledge_unavailable"])
        self.assertFalse(result["knowledge_used"])
        self.assertNotIn("证据不足", model.call_args.kwargs["messages"][0]["content"])

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
                "_search_external_knowledge",
                return_value=self.citations,
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


if __name__ == "__main__":
    unittest.main()

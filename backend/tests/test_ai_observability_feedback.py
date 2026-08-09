import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException

from api import routes
from api.schemas import MessageFeedbackRequest


class AiObservabilityFeedbackTests(unittest.TestCase):
    def test_run_record_contains_metadata_but_no_message_bodies(self):
        query = MagicMock()
        query.insert.return_value = query
        query.execute.return_value = SimpleNamespace(
            data=[
                {
                    "id": "run-1",
                    "status": "succeeded",
                    "latency_ms": 120,
                }
            ]
        )
        service = MagicMock()
        service.table.return_value = query

        with patch.object(routes, "database", return_value=service):
            result = routes._record_ai_run(
                user_id="user-1",
                module="problem-decomposition",
                provider="xunfei-star-agent",
                status="succeeded",
                latency_ms=120,
                retrieval_count=3,
            )

        payload = query.insert.call_args.args[0]
        self.assertEqual(result["id"], "run-1")
        self.assertEqual(payload["retrieval_count"], 3)
        self.assertNotIn("prompt", payload)
        self.assertNotIn("content", payload)
        self.assertNotIn("reply", payload)

    def test_feedback_is_upserted_as_pending_review(self):
        run_query = MagicMock()
        run_query.select.return_value = run_query
        run_query.eq.return_value = run_query
        run_query.limit.return_value = run_query
        run_query.execute.return_value = SimpleNamespace(data=[{"id": "run-1"}])

        feedback_query = MagicMock()
        feedback_query.upsert.return_value = feedback_query
        feedback_query.execute.return_value = SimpleNamespace(
            data=[
                {
                    "id": "feedback-1",
                    "message_id": "message-1",
                    "rating": "unhelpful",
                    "comment": "缺少证据",
                    "review_status": "pending",
                }
            ]
        )
        service = MagicMock()
        service.table.side_effect = lambda name: (
            run_query if name == "ai_runs" else feedback_query
        )

        with (
            patch.object(
                routes,
                "require_owned_row",
                return_value={
                    "id": "message-1",
                    "conversation_id": "conversation-1",
                    "user_id": "user-1",
                    "role": "assistant",
                },
            ),
            patch.object(routes, "database", return_value=service),
        ):
            result = routes.upsert_message_feedback(
                "message-1",
                MessageFeedbackRequest(rating="unhelpful", comment=" 缺少证据 "),
                user=SimpleNamespace(id="user-1"),
            )

        payload = feedback_query.upsert.call_args.args[0]
        self.assertEqual(result["review_status"], "pending")
        self.assertEqual(payload["comment"], "缺少证据")
        self.assertEqual(payload["ai_run_id"], "run-1")
        self.assertEqual(
            feedback_query.upsert.call_args.kwargs["on_conflict"],
            "message_id,user_id",
        )

    def test_user_messages_cannot_be_rated(self):
        with (
            patch.object(
                routes,
                "require_owned_row",
                return_value={
                    "id": "message-1",
                    "conversation_id": "conversation-1",
                    "user_id": "user-1",
                    "role": "user",
                },
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            routes.upsert_message_feedback(
                "message-1",
                MessageFeedbackRequest(rating="helpful"),
                user=SimpleNamespace(id="user-1"),
            )

        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()

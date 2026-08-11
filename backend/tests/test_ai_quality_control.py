import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException

from api import dependencies, routes
from api.schemas import EvaluationRunRequest, FeedbackReviewRequest
from services.evaluation_service import evaluate_rag_retrieval_cases


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "rag_quality_cases.json"


class AiQualityControlTests(unittest.TestCase):
    def test_admin_role_comes_from_server_profile(self):
        user = SimpleNamespace(id="admin-1", user_metadata={"role": "user"})
        with patch.object(
            dependencies,
            "get_or_create_profile",
            return_value={"id": "admin-1", "role": "admin"},
        ):
            self.assertIs(dependencies.get_current_admin(user=user), user)

    def test_non_admin_is_rejected_even_if_metadata_claims_admin(self):
        user = SimpleNamespace(id="user-1", user_metadata={"role": "admin"})
        with (
            patch.object(
                dependencies,
                "get_or_create_profile",
                return_value={"id": "user-1", "role": "user"},
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            dependencies.get_current_admin(user=user)
        self.assertEqual(raised.exception.status_code, 403)

    def test_fixed_offline_suite_meets_quality_floor(self):
        cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        normalized = [
            {
                "id": f"case-{index}",
                "input": {
                    "query": item["query"],
                    "original": item["original"],
                    "rewritten": item["rewritten"],
                },
                "expected": {"relevant_ids": item["relevant_ids"]},
            }
            for index, item in enumerate(cases, start=1)
        ]
        result = evaluate_rag_retrieval_cases(normalized, top_k=3)
        self.assertEqual(result["case_count"], 3)
        self.assertEqual(result["failed_count"], 0)
        self.assertGreaterEqual(result["metrics"]["recall_at_3"], 1.0)
        self.assertGreaterEqual(result["metrics"]["mrr"], 0.9)

    def test_real_model_evaluation_is_blocked_before_database_access(self):
        with (
            patch.object(routes, "database") as database,
            self.assertRaises(HTTPException) as raised,
        ):
            routes.run_quality_evaluation(
                EvaluationRunRequest(
                    suite_slug="rag-retrieval-baseline",
                    mode="real-model",
                ),
                user=SimpleNamespace(id="admin-1"),
            )
        self.assertEqual(raised.exception.status_code, 409)
        database.assert_not_called()

    def test_real_model_request_requires_explicit_confirmation(self):
        request = EvaluationRunRequest(
            suite_slug="xunfei-real-model-smoke",
            mode="real-model",
        )
        self.assertFalse(request.confirm_external_calls)

    def test_admin_review_records_reviewer_and_status(self):
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.limit.return_value = query
        query.update.return_value = query
        query.execute.side_effect = [
            SimpleNamespace(data=[{"id": "feedback-1"}]),
            SimpleNamespace(
                data=[
                    {
                        "id": "feedback-1",
                        "user_id": "user-1",
                        "conversation_id": "conversation-1",
                        "message_id": "message-1",
                        "rating": "unhelpful",
                        "review_status": "reviewed",
                        "reviewed_by": "admin-1",
                    }
                ]
            ),
        ]
        service = MagicMock()
        service.table.return_value = query

        with (
            patch.object(routes, "database", return_value=service),
            patch.object(routes, "record_activity"),
        ):
            result = routes.review_message_feedback(
                "feedback-1",
                FeedbackReviewRequest(
                    review_status="reviewed",
                    review_note="可用于后续人工整理",
                ),
                user=SimpleNamespace(id="admin-1"),
            )

        payload = query.update.call_args.args[0]
        self.assertEqual(result["review_status"], "reviewed")
        self.assertEqual(payload["reviewed_by"], "admin-1")
        self.assertEqual(payload["review_note"], "可用于后续人工整理")


if __name__ == "__main__":
    unittest.main()

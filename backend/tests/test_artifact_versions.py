import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from api import routes


def database_with_rows(rows):
    query = MagicMock()
    query.select.return_value = query
    query.insert.return_value = query
    query.update.return_value = query
    query.eq.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.execute.return_value = SimpleNamespace(data=rows)
    service = MagicMock()
    service.table.return_value = query
    return service, query


class ArtifactVersionTests(unittest.TestCase):
    def test_generated_artifact_starts_as_version_one_draft(self):
        service, query = database_with_rows([{"id": "artifact-1"}])
        with patch.object(routes, "database", return_value=service):
            routes._save_artifact(
                "user-1",
                "research-decomposition",
                "研究问题",
                {"direction": "研究问题"},
                {"core_question": "问题", "sub_questions": []},
            )

        inserted = query.insert.call_args.args[0]
        self.assertEqual(inserted["review_status"], "draft")
        self.assertEqual(inserted["version"], 1)
        self.assertEqual(inserted["id"], inserted["version_group_id"])

    def test_revision_preserves_group_and_increments_latest_version(self):
        service, query = database_with_rows([{"id": "artifact-4"}])
        source = {
            "id": "artifact-1",
            "user_id": "user-1",
            "artifact_type": "research-decomposition",
            "title": "研究问题",
            "input": {"direction": "研究问题"},
            "version_group_id": "artifact-1",
            "version": 1,
        }
        latest = {"id": "artifact-3", "version": 3}
        with patch.object(routes, "database", return_value=service):
            routes._insert_artifact_revision(
                source,
                latest,
                "user-1",
                title="修订问题",
                content={"core_question": "修订问题", "sub_questions": []},
                revision_note="人工修订",
            )

        inserted = query.insert.call_args.args[0]
        self.assertEqual(inserted["version_group_id"], "artifact-1")
        self.assertEqual(inserted["version"], 4)
        self.assertEqual(inserted["parent_version_id"], "artifact-1")
        self.assertEqual(inserted["review_status"], "draft")

    def test_linked_workflow_uses_latest_confirmed_version(self):
        source = {
            "id": "artifact-1",
            "artifact_type": "research-decomposition",
        }
        confirmed = {
            "id": "artifact-2",
            "artifact_type": "research-decomposition",
            "review_status": "confirmed",
            "version": 2,
        }
        with (
            patch.object(routes, "require_owned_row", return_value=source),
            patch.object(routes, "_latest_confirmed_artifact", return_value=confirmed),
        ):
            resolved = routes._resolve_confirmed_artifact(
                "artifact-1",
                "user-1",
                "research-decomposition",
            )

        self.assertEqual(resolved["id"], "artifact-2")

    def test_linked_workflow_rejects_group_without_confirmed_version(self):
        source = {
            "id": "artifact-1",
            "artifact_type": "research-decomposition",
        }
        with (
            patch.object(routes, "require_owned_row", return_value=source),
            patch.object(routes, "_latest_confirmed_artifact", return_value=None),
        ):
            with self.assertRaises(HTTPException) as raised:
                routes._resolve_confirmed_artifact(
                    "artifact-1",
                    "user-1",
                    "research-decomposition",
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("确认上游产物", raised.exception.detail)

    def test_revision_content_is_validated_by_artifact_type(self):
        valid = routes._validate_artifact_content(
            "research-decomposition",
            {
                "core_question": "如何验证方案？",
                "sub_questions": [
                    {
                        "id": "rq-1",
                        "question": "数据是否充分？",
                        "feasibility": "high",
                        "datasets": [],
                        "papers": [],
                    }
                ],
            },
            None,
        )
        self.assertEqual(valid["sub_questions"][0]["question"], "数据是否充分？")

        with self.assertRaises(HTTPException) as raised:
            routes._validate_artifact_content(
                "research-decomposition",
                {"core_question": "缺少子问题"},
                None,
            )
        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()

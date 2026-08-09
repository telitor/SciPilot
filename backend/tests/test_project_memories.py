import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from api import routes
from api.schemas import (
    CreateProjectMemoryRequest,
    ProjectAssignmentRequest,
    UpdateProjectMemoryRequest,
)


def database_with_rows(rows, *, count=None):
    query = MagicMock()
    query.select.return_value = query
    query.insert.return_value = query
    query.update.return_value = query
    query.eq.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.execute.return_value = SimpleNamespace(
        data=rows,
        count=len(rows) if count is None else count,
    )
    service = MagicMock()
    service.table.return_value = query
    return service, query


class ProjectMemoryTests(unittest.TestCase):
    def test_create_manual_memory_uses_authenticated_owner(self):
        created = {
            "id": "memory-1",
            "project_id": "project-1",
            "title": "评测约束",
        }
        service, query = database_with_rows([created])
        payload = CreateProjectMemoryRequest(
            memory_type="constraint",
            title="评测约束",
            content="统一使用固定测试集。",
        )

        with (
            patch.object(routes, "database", return_value=service),
            patch.object(routes, "_require_project") as require_project,
            patch.object(routes, "record_activity"),
        ):
            result = routes.create_project_memory(
                "project-1",
                payload,
                user=SimpleNamespace(id="user-1"),
            )

        require_project.assert_called_once_with("project-1", "user-1", writable=True)
        inserted = query.insert.call_args.args[0]
        self.assertEqual(inserted["user_id"], "user-1")
        self.assertEqual(inserted["source_type"], "manual")
        self.assertEqual(inserted["status"], "active")
        self.assertEqual(result["id"], "memory-1")

    def test_memory_cannot_be_updated_through_another_project(self):
        payload = UpdateProjectMemoryRequest(status="archived")
        with (
            patch.object(routes, "_require_project"),
            patch.object(
                routes,
                "require_owned_row",
                return_value={"id": "memory-1", "project_id": "project-2"},
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                routes.update_project_memory(
                    "project-1",
                    "memory-1",
                    payload,
                    user=SimpleNamespace(id="user-1"),
                )

        self.assertEqual(raised.exception.status_code, 404)

    def test_active_memories_are_formatted_for_agent_context(self):
        service, query = database_with_rows(
            [
                {
                    "memory_type": "decision",
                    "title": "采用 F1 指标",
                    "content": "类别不平衡，因此主指标使用 macro-F1。",
                    "source_type": "manual",
                }
            ]
        )
        with patch.object(routes, "database", return_value=service):
            blocks = routes._active_project_memory_blocks("project-1", "user-1")

        self.assertIn("采用 F1 指标", blocks[0])
        self.assertIn("macro-F1", blocks[0])
        query.eq.assert_any_call("user_id", "user-1")
        query.eq.assert_any_call("project_id", "project-1")
        query.eq.assert_any_call("status", "active")

    def test_confirmed_artifact_creates_source_aware_memory(self):
        artifact = {
            "id": "artifact-2",
            "user_id": "user-1",
            "project_id": "project-1",
            "artifact_type": "result-analysis",
            "title": "实验结果",
            "content": {"interpretation": "方法优于基线。", "suggestions": []},
            "review_status": "confirmed",
            "version_group_id": "artifact-1",
            "version": 2,
        }
        existing_service, existing_query = database_with_rows([])
        insert_query = MagicMock()
        insert_query.insert.return_value = insert_query
        insert_query.execute.return_value = SimpleNamespace(data=[{"id": "memory-1"}])
        service = MagicMock()
        service.table.side_effect = [existing_query, insert_query]

        with patch.object(routes, "database", return_value=service):
            synced = routes._sync_artifact_memory(artifact, "user-1")

        self.assertTrue(synced)
        inserted = insert_query.insert.call_args.args[0]
        self.assertEqual(inserted["source_id"], "artifact-1")
        self.assertEqual(inserted["source_version"], 2)
        self.assertEqual(inserted["memory_type"], "artifact-summary")

    def test_sync_preserves_user_archived_status(self):
        artifact = {
            "id": "artifact-3",
            "project_id": "project-1",
            "artifact_type": "research-decomposition",
            "title": "问题树",
            "content": {"core_question": "新问题", "sub_questions": []},
            "review_status": "confirmed",
            "version_group_id": "artifact-1",
            "version": 3,
        }
        lookup_query = MagicMock()
        lookup_query.select.return_value = lookup_query
        lookup_query.eq.return_value = lookup_query
        lookup_query.limit.return_value = lookup_query
        lookup_query.execute.return_value = SimpleNamespace(
            data=[{"id": "memory-1", "status": "archived"}]
        )
        update_query = MagicMock()
        update_query.update.return_value = update_query
        update_query.eq.return_value = update_query
        update_query.execute.return_value = SimpleNamespace(data=[{"id": "memory-1"}])
        service = MagicMock()
        service.table.side_effect = [lookup_query, update_query]

        with patch.object(routes, "database", return_value=service):
            synced = routes._sync_artifact_memory(artifact, "user-1")

        self.assertTrue(synced)
        updates = update_query.update.call_args.args[0]
        self.assertEqual(updates["source_version"], 3)
        self.assertNotIn("status", updates)

    def test_assigning_artifact_moves_full_version_group_and_refreshes_memory(self):
        artifact = {
            "id": "artifact-2",
            "user_id": "user-1",
            "project_id": "project-2",
            "version_group_id": "artifact-1",
        }
        service, query = database_with_rows([artifact])
        confirmed = {**artifact, "review_status": "confirmed", "version": 2}

        with (
            patch.object(routes, "database", return_value=service),
            patch.object(routes, "require_owned_row", return_value=artifact),
            patch.object(routes, "_validated_project_id", return_value="project-2"),
            patch.object(routes, "_reassign_artifact_memory") as reassign,
            patch.object(routes, "_latest_confirmed_artifact", return_value=confirmed),
            patch.object(routes, "_sync_artifact_memory") as sync,
        ):
            result = routes.assign_project_asset(
                "artifact",
                "artifact-2",
                ProjectAssignmentRequest(project_id="22222222-2222-2222-2222-222222222222"),
                user=SimpleNamespace(id="user-1"),
            )

        query.eq.assert_any_call("version_group_id", "artifact-1")
        reassign.assert_called_once_with("artifact-1", "user-1", "project-2")
        sync.assert_called_once_with(confirmed, "user-1")
        self.assertEqual(result["id"], "artifact-2")


if __name__ == "__main__":
    unittest.main()

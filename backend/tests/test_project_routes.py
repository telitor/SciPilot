from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, call, patch
from uuid import UUID

from fastapi import HTTPException

from api import routes
from api.schemas import (
    CreateConversationRequest,
    CreateResearchProjectRequest,
    ProjectAssignmentRequest,
)


PROJECT_ID = UUID("11111111-1111-1111-1111-111111111111")


def query_with_result(data):
    query = MagicMock()
    query.insert.return_value = query
    query.update.return_value = query
    query.eq.return_value = query
    query.execute.return_value = SimpleNamespace(data=data, count=len(data))
    service = MagicMock()
    service.table.return_value = query
    return service, query


class ResearchProjectRouteTests(unittest.TestCase):
    def test_archived_project_cannot_receive_new_assets(self):
        archived = {"id": str(PROJECT_ID), "user_id": "user-1", "status": "archived"}
        with patch.object(routes, "require_owned_row", return_value=archived):
            with self.assertRaises(HTTPException) as raised:
                routes._validated_project_id(PROJECT_ID, "user-1")

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("已归档", raised.exception.detail)

    def test_create_project_always_uses_authenticated_user(self):
        project = {
            "id": str(PROJECT_ID),
            "user_id": "user-1",
            "name": "可靠性研究",
            "status": "active",
        }
        service, query = query_with_result([project])
        payload = CreateResearchProjectRequest(name="可靠性研究")

        with (
            patch.object(routes, "database", return_value=service),
            patch.object(routes, "record_activity") as record_activity,
        ):
            result = routes.create_project(payload, user=SimpleNamespace(id="user-1"))

        inserted = query.insert.call_args.args[0]
        self.assertEqual(inserted["user_id"], "user-1")
        self.assertEqual(inserted["status"], "active")
        self.assertEqual(result["id"], str(PROJECT_ID))
        self.assertEqual(record_activity.call_args.kwargs["project_id"], str(PROJECT_ID))

    def test_assign_asset_checks_asset_and_project_ownership(self):
        updated = {"id": "paper-1", "project_id": str(PROJECT_ID)}
        service, query = query_with_result([updated])
        payload = ProjectAssignmentRequest(project_id=PROJECT_ID)
        project = {"id": str(PROJECT_ID), "user_id": "user-1", "status": "active"}

        with (
            patch.object(routes, "database", return_value=service),
            patch.object(routes, "require_owned_row", side_effect=[{"id": "paper-1"}, project]) as owned,
        ):
            result = routes.assign_project_asset(
                "paper",
                "paper-1",
                payload,
                user=SimpleNamespace(id="user-1"),
            )

        self.assertEqual(
            owned.call_args_list,
            [
                call("papers", "paper-1", "user-1"),
                call(
                    "research_projects",
                    str(PROJECT_ID),
                    "user-1",
                    columns=routes.PROJECT_COLUMNS,
                ),
            ],
        )
        query.update.assert_called_once_with({"project_id": str(PROJECT_ID)})
        self.assertEqual(result["project_id"], str(PROJECT_ID))

    def test_conversation_persists_validated_project(self):
        created = {
            "id": "conversation-1",
            "agent_id": "agent-1",
            "project_id": str(PROJECT_ID),
        }
        service, query = query_with_result([created])
        payload = CreateConversationRequest(
            title="项目对话",
            module="research",
            agent_id="agent-1",
            project_id=PROJECT_ID,
        )

        with (
            patch.object(routes, "database", return_value=service),
            patch.object(routes, "_validated_project_id", return_value=str(PROJECT_ID)) as validate,
            patch.object(routes, "_pick_agent", return_value={"id": "agent-1"}),
        ):
            result = routes.create_conversation(payload, user=SimpleNamespace(id="user-1"))

        validate.assert_called_once_with(PROJECT_ID, "user-1")
        inserted = query.insert.call_args.args[0]
        self.assertEqual(inserted["project_id"], str(PROJECT_ID))
        self.assertEqual(result["messages"], [])

    def test_linked_artifact_cannot_override_its_project(self):
        other_project_id = UUID("22222222-2222-2222-2222-222222222222")

        with self.assertRaises(HTTPException) as raised:
            routes._resolve_linked_project_id(
                PROJECT_ID,
                other_project_id,
                "user-1",
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("上游产物", raised.exception.detail)

    def test_project_stage_advances_only_after_successful_output(self):
        service, query = query_with_result([{"id": str(PROJECT_ID)}])
        project = {
            "id": str(PROJECT_ID),
            "user_id": "user-1",
            "status": "active",
            "current_stage": "literature",
        }

        with (
            patch.object(routes, "database", return_value=service),
            patch.object(routes, "_require_project", return_value=project),
        ):
            advanced = routes._advance_project_stage(
                str(PROJECT_ID),
                "user-1",
                "question",
            )

        self.assertTrue(advanced)
        query.update.assert_called_once_with({"current_stage": "question"})

    def test_project_stage_never_moves_backwards(self):
        project = {
            "id": str(PROJECT_ID),
            "user_id": "user-1",
            "status": "active",
            "current_stage": "reproduction",
        }

        with (
            patch.object(routes, "database") as database,
            patch.object(routes, "_require_project", return_value=project),
        ):
            advanced = routes._advance_project_stage(
                str(PROJECT_ID),
                "user-1",
                "question",
            )

        self.assertFalse(advanced)
        database.assert_not_called()


if __name__ == "__main__":
    unittest.main()

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from api import routes


def task(position: int, status: str, *, task_key: str | None = None) -> dict:
    spec = routes.WORKFLOW_TASK_SPECS[position - 1]
    return {
        "id": f"task-{position}",
        "workflow_id": "workflow-1",
        "user_id": "user-1",
        "project_id": "project-1",
        "task_key": task_key or spec["task_key"],
        "title": spec["title"],
        "agent_category": spec["agent_category"],
        "position": position,
        "status": status,
    }


class AgentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = {
            "id": "workflow-1",
            "project_id": "project-1",
            "user_id": "user-1",
            "name": "测试任务流",
            "status": "active",
        }

    def test_fixed_workflow_has_five_ordered_manual_stages(self):
        self.assertEqual(
            [item["task_key"] for item in routes.WORKFLOW_TASK_SPECS],
            [
                "paper-reading",
                "problem-decomposition",
                "project-planning",
                "code-reproduction",
                "result-interpretation",
            ],
        )
        self.assertEqual(
            [item["position"] for item in routes.WORKFLOW_TASK_SPECS],
            [1, 2, 3, 4, 5],
        )

    def test_blocked_task_cannot_start_before_upstream_approval(self):
        blocked = task(2, "blocked")
        with (
            patch.object(routes, "_require_project"),
            patch.object(routes, "_workflow_for_project", return_value=self.workflow),
            patch.object(
                routes,
                "_sync_project_workflow",
                return_value=(self.workflow, [blocked]),
            ),
            patch.object(routes, "_require_workflow_task", return_value=blocked),
            patch.object(routes, "_update_workflow_task") as update_task,
        ):
            with self.assertRaises(HTTPException) as raised:
                routes.start_project_workflow_task(
                    "project-1",
                    "task-2",
                    user=SimpleNamespace(id="user-1"),
                )

        self.assertEqual(raised.exception.status_code, 409)
        update_task.assert_not_called()

    def test_opening_ready_task_does_not_claim_execution_before_job_exists(self):
        ready = task(1, "ready")
        with (
            patch.object(routes, "_require_project"),
            patch.object(routes, "_workflow_for_project", return_value=self.workflow),
            patch.object(
                routes,
                "_sync_project_workflow",
                side_effect=[(self.workflow, [ready]), (self.workflow, [ready])],
            ),
            patch.object(routes, "_require_workflow_task", return_value=ready),
            patch.object(
                routes,
                "_update_workflow_task",
            ) as update_task,
        ):
            result = routes.start_project_workflow_task(
                "project-1",
                "task-1",
                user=SimpleNamespace(id="user-1"),
            )

        self.assertEqual(result["tasks"][0]["status"], "ready")
        update_task.assert_not_called()

    def test_confirmed_output_completes_node_and_unlocks_only_next_node(self):
        tasks = [
            task(1, "completed"),
            task(2, "awaiting_approval"),
            task(3, "blocked"),
            task(4, "blocked"),
            task(5, "blocked"),
        ]

        def merge(current, _user_id, updates):
            return {**current, **updates}

        with (
            patch.object(routes, "_workflow_tasks", return_value=tasks),
            patch.object(
                routes,
                "_latest_workflow_output",
                side_effect=[
                    {"id": "artifact-1", "review_status": "confirmed"},
                    None,
                ],
            ),
            patch.object(routes, "_update_workflow_task", side_effect=merge),
        ):
            _, synchronized = routes._sync_project_workflow(
                self.workflow,
                "user-1",
            )

        self.assertEqual(synchronized[0]["status"], "completed")
        self.assertEqual(synchronized[1]["status"], "completed")
        self.assertEqual(synchronized[2]["status"], "ready")
        self.assertTrue(all(item["status"] == "blocked" for item in synchronized[3:]))

    def test_failed_retry_reuses_only_current_linked_job(self):
        failed = {**task(3, "failed"), "research_job_id": "job-3"}
        retried = {**failed, "status": "in_progress", "error_message": None}
        with (
            patch.object(routes, "_require_project"),
            patch.object(routes, "_workflow_for_project", return_value=self.workflow),
            patch.object(
                routes,
                "_sync_project_workflow",
                side_effect=[(self.workflow, [failed]), (self.workflow, [retried])],
            ),
            patch.object(routes, "_require_workflow_task", return_value=failed),
            patch.object(routes, "retry_owned_research_job") as retry_job,
            patch.object(routes, "_update_workflow_task") as update_task,
        ):
            result = routes.retry_project_workflow_task(
                "project-1",
                "task-3",
                user=SimpleNamespace(id="user-1"),
            )

        retry_job.assert_called_once_with("job-3", "user-1")
        self.assertEqual(update_task.call_args.args[2]["status"], "in_progress")
        self.assertEqual(result["tasks"][0]["status"], "in_progress")


if __name__ == "__main__":
    unittest.main()

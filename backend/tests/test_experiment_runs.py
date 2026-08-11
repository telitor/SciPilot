import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from api import routes
from api.schemas import CreateExperimentRunRequest, UpdateExperimentRunRequest


def database_with_result(rows):
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


class ExperimentRunTests(unittest.TestCase):
    def test_create_run_is_linked_to_confirmed_code_artifact(self):
        stored = {
            "id": "run-1",
            "project_id": "project-1",
            "code_artifact_id": "code-2",
            "execution_mode": "manual-evidence",
            "status": "planned",
            "commit_sha": "abcdef1",
            "command": "python train.py",
            "environment": {"runtime": "Python 3.11"},
            "output_files": [],
        }
        service, query = database_with_result([stored])
        payload = CreateExperimentRunRequest(
            code_artifact_id="code-1",
            commit_sha="ABCDEF1",
            command="python train.py",
            environment={"runtime": "Python 3.11"},
        )
        with (
            patch.object(
                routes,
                "_resolve_confirmed_artifact",
                return_value={"id": "code-2", "project_id": "project-1"},
            ),
            patch.object(routes, "database", return_value=service),
            patch.object(routes, "record_activity"),
        ):
            result = routes.create_experiment_run(
                payload,
                user=SimpleNamespace(id="user-1"),
            )

        inserted = query.insert.call_args.args[0]
        self.assertEqual(inserted["code_artifact_id"], "code-2")
        self.assertEqual(inserted["project_id"], "project-1")
        self.assertEqual(inserted["commit_sha"], "abcdef1")
        self.assertEqual(result["status"], "planned")

    def test_create_run_rejects_sensitive_environment_fields(self):
        payload = CreateExperimentRunRequest(
            code_artifact_id="code-1",
            commit_sha="abcdef1",
            command="python train.py",
            environment={"API_KEY": "must-not-be-stored"},
        )
        with patch.object(
            routes,
            "_resolve_confirmed_artifact",
            return_value={"id": "code-1", "project_id": None},
        ):
            with self.assertRaises(HTTPException) as raised:
                routes.create_experiment_run(
                    payload,
                    user=SimpleNamespace(id="user-1"),
                )

        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("API Key", raised.exception.detail)

    def test_update_run_enforces_state_machine(self):
        payload = UpdateExperimentRunRequest(status="running")
        with patch.object(
            routes,
            "_owned_experiment_run",
            return_value={"id": "run-1", "status": "succeeded"},
        ):
            with self.assertRaises(HTTPException) as raised:
                routes.update_experiment_run(
                    "run-1",
                    payload,
                    user=SimpleNamespace(id="user-1"),
                )

        self.assertEqual(raised.exception.status_code, 409)

    def test_result_link_requires_successful_owned_run(self):
        with patch.object(
            routes,
            "_owned_experiment_run",
            return_value={"id": "run-1", "status": "running"},
        ):
            with self.assertRaises(HTTPException) as raised:
                routes._resolve_experiment_run_for_results(
                    "run-1",
                    "user-1",
                    "code-1",
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("成功证据", raised.exception.detail)

    def test_result_link_rejects_different_code_artifact(self):
        with patch.object(
            routes,
            "_owned_experiment_run",
            return_value={
                "id": "run-1",
                "status": "succeeded",
                "code_artifact_id": "code-2",
            },
        ):
            with self.assertRaises(HTTPException) as raised:
                routes._resolve_experiment_run_for_results(
                    "run-1",
                    "user-1",
                    "code-1",
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("不一致", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()

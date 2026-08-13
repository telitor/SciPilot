import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from api import routes
from api.schemas import (
    AnalyzeExperimentResultFileRequest,
    CreateExperimentRunRequest,
    UpdateExperimentRunRequest,
)
from services.sandbox_execution_service import CapturedResultFile


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
    def test_tabular_stats_report_missing_invalid_and_student_t_interval(self):
        stats = routes._tabular_stats(
            [
                {"loss": "1", "accuracy": "0.8"},
                {"loss": "3", "accuracy": ""},
                {"loss": "bad", "accuracy": None},
            ]
        )

        loss = next(item for item in stats if item["metric"] == "loss")
        self.assertEqual(loss["count"], 2)
        self.assertEqual(loss["missing_count"], 0)
        self.assertEqual(loss["invalid_count"], 1)
        self.assertEqual(loss["ci_method"], "student-t")
        self.assertAlmostEqual(loss["ci95"][0], -10.706, places=3)
        self.assertAlmostEqual(loss["ci95"][1], 14.706, places=3)

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

    def test_sandboxed_run_requires_runtime_to_be_enabled(self):
        payload = CreateExperimentRunRequest(
            code_artifact_id="code-1",
            execution_mode="sandboxed-docker",
            commit_sha="abcdef1",
            command="python train.py",
        )
        with (
            patch.object(
                routes,
                "_resolve_confirmed_artifact",
                return_value={"id": "code-1", "project_id": None},
            ),
            patch.object(routes, "docker_execution_enabled", return_value=False),
        ):
            with self.assertRaises(HTTPException) as raised:
                routes.create_experiment_run(
                    payload,
                    user=SimpleNamespace(id="user-1"),
                )

        self.assertEqual(raised.exception.status_code, 503)

    def test_sandboxed_run_rejects_unapproved_command(self):
        payload = CreateExperimentRunRequest(
            code_artifact_id="code-1",
            execution_mode="sandboxed-docker",
            commit_sha="abcdef1",
            command="powershell Get-Process",
        )
        with (
            patch.object(
                routes,
                "_resolve_confirmed_artifact",
                return_value={"id": "code-1", "project_id": None},
            ),
            patch.object(routes, "docker_execution_enabled", return_value=True),
        ):
            with self.assertRaises(HTTPException) as raised:
                routes.create_experiment_run(
                    payload,
                    user=SimpleNamespace(id="user-1"),
                )

        self.assertEqual(raised.exception.status_code, 422)

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

    def test_manual_run_evidence_cannot_spoof_private_storage_fields(self):
        payload = UpdateExperimentRunRequest.model_validate(
            {
                "status": "succeeded",
                "exit_code": 0,
                "output_files": [
                    {
                        "name": "metrics.csv",
                        "relative_path": "outputs/metrics.csv",
                        "id": "forged-file-id",
                        "stored": True,
                        "analyzable": True,
                    }
                ],
            }
        )

        output_file = payload.model_dump()["output_files"][0]
        self.assertNotIn("id", output_file)
        self.assertNotIn("stored", output_file)
        self.assertNotIn("analyzable", output_file)

    def test_captured_result_file_is_uploaded_and_linked_to_output_metadata(self):
        raw = b"epoch,loss\n1,0.5\n"
        checksum = __import__("hashlib").sha256(raw).hexdigest()
        storage_bucket = MagicMock()
        metadata_query = MagicMock()
        metadata_query.insert.return_value = metadata_query
        metadata_query.execute.return_value = SimpleNamespace(data=[{"id": "saved"}])
        service = MagicMock()
        service.storage.from_.return_value = storage_bucket
        service.table.return_value = metadata_query

        with (
            patch.object(routes, "database", return_value=service),
            patch.object(routes.uuid, "uuid4", return_value="file-1"),
        ):
            output_files, warning = routes._persist_experiment_result_files(
                run={"id": "run-1", "project_id": "project-1"},
                user_id="user-1",
                output_files=[
                    {
                        "name": "metrics.csv",
                        "relative_path": "outputs/metrics.csv",
                        "size_bytes": len(raw),
                        "sha256": checksum,
                        "media_type": "text/csv",
                    }
                ],
                captured_files=[
                    CapturedResultFile(
                        name="metrics.csv",
                        relative_path="outputs/metrics.csv",
                        media_type="text/csv",
                        size_bytes=len(raw),
                        sha256=checksum,
                        content=raw,
                    )
                ],
            )

        self.assertIsNone(warning)
        self.assertEqual(output_files[0]["id"], "file-1")
        self.assertTrue(output_files[0]["stored"])
        self.assertTrue(output_files[0]["analyzable"])
        storage_bucket.upload.assert_called_once()
        inserted = metadata_query.insert.call_args.args[0]
        self.assertEqual(inserted["experiment_run_id"], "run-1")
        self.assertEqual(inserted["checksum_sha256"], checksum)

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

    def test_stored_run_result_is_verified_and_enqueued(self):
        raw = b"epoch,loss\n1,0.5\n2,0.25\n"
        checksum = __import__("hashlib").sha256(raw).hexdigest()
        storage_bucket = MagicMock()
        storage_bucket.download.return_value = raw
        service = MagicMock()
        service.storage.from_.return_value = storage_bucket
        payload = AnalyzeExperimentResultFileRequest(
            experiment_run_id="run-1",
            result_file_id="file-1",
        )
        run = {
            "id": "run-1",
            "status": "succeeded",
            "project_id": "project-1",
            "code_artifact_id": "code-1",
        }
        result_file = {
            "id": "file-1",
            "experiment_run_id": "run-1",
            "file_name": "metrics.csv",
            "relative_path": "outputs/metrics.csv",
            "storage_path": "user-1/run-1/file-1-metrics.csv",
            "media_type": "text/csv",
            "size_bytes": len(raw),
            "checksum_sha256": checksum,
            "result_artifact_id": None,
        }
        with (
            patch.object(routes, "_resolve_experiment_run_for_results", return_value=run),
            patch.object(routes, "require_owned_row", return_value=result_file),
            patch.object(routes, "database", return_value=service),
            patch.object(routes, "_enqueue_agent_job", return_value={"id": "job-1"}) as enqueue,
        ):
            response = routes.enqueue_stored_result_analysis(
                payload,
                user=SimpleNamespace(id="user-1"),
            )

        self.assertEqual(response, {"id": "job-1"})
        input_data = enqueue.call_args.kwargs["input_data"]
        self.assertEqual(input_data["result_file"]["id"], "file-1")
        self.assertEqual(input_data["stats"][0]["ci_method"], "student-t")

    def test_stored_run_result_rejects_checksum_mismatch(self):
        storage_bucket = MagicMock()
        storage_bucket.download.return_value = b"epoch,loss\n1,0.5\n"
        service = MagicMock()
        service.storage.from_.return_value = storage_bucket
        payload = AnalyzeExperimentResultFileRequest(
            experiment_run_id="run-1",
            result_file_id="file-1",
        )
        with (
            patch.object(
                routes,
                "_resolve_experiment_run_for_results",
                return_value={
                    "id": "run-1",
                    "status": "succeeded",
                    "project_id": None,
                    "code_artifact_id": "code-1",
                },
            ),
            patch.object(
                routes,
                "require_owned_row",
                return_value={
                    "id": "file-1",
                    "experiment_run_id": "run-1",
                    "storage_path": "user-1/run-1/file.csv",
                    "checksum_sha256": "0" * 64,
                },
            ),
            patch.object(routes, "database", return_value=service),
        ):
            with self.assertRaises(HTTPException) as raised:
                routes.enqueue_stored_result_analysis(
                    payload,
                    user=SimpleNamespace(id="user-1"),
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("完整性", raised.exception.detail)

    def test_linking_analysis_preserves_private_storage_flags(self):
        service, query = database_with_result([{"id": "run-1"}])
        run = {
            "id": "run-1",
            "output_files": [
                {
                    "id": "file-1",
                    "name": "metrics.csv",
                    "relative_path": "outputs/metrics.csv",
                    "stored": True,
                    "analyzable": True,
                }
            ],
        }
        with patch.object(routes, "database", return_value=service):
            routes._link_result_artifact_to_experiment_run(
                run,
                "user-1",
                "artifact-1",
                {
                    "id": "file-1",
                    "name": "metrics.csv",
                    "sha256": "a" * 64,
                },
            )

        updated_run = query.update.call_args_list[0].args[0]
        linked_file = updated_run["output_files"][0]
        self.assertTrue(linked_file["stored"])
        self.assertTrue(linked_file["analyzable"])
        self.assertEqual(linked_file["sha256"], "a" * 64)


if __name__ == "__main__":
    unittest.main()

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from fastapi import HTTPException

from api import routes
from services import research_job_service


def service_with_rows(rows):
    query = MagicMock()
    query.select.return_value = query
    query.insert.return_value = query
    query.update.return_value = query
    query.eq.return_value = query
    query.limit.return_value = query
    query.order.return_value = query
    query.execute.return_value = SimpleNamespace(data=rows)
    service = MagicMock()
    service.table.return_value = query
    return service, query


class ResearchJobServiceTests(unittest.TestCase):
    def test_owned_job_lookup_always_filters_authenticated_user(self):
        service, query = service_with_rows([{"id": "job-1", "user_id": "user-1"}])
        with patch.object(research_job_service, "_database", return_value=service):
            job = research_job_service.get_owned_research_job("job-1", "user-1")

        self.assertEqual(job["id"], "job-1")
        self.assertIn(call("id", "job-1"), query.eq.call_args_list)
        self.assertIn(call("user_id", "user-1"), query.eq.call_args_list)

    def test_transient_failure_is_requeued_before_attempt_limit(self):
        service, query = service_with_rows(
            [{"id": "job-1", "status": "pending", "attempts": 1, "max_attempts": 3}]
        )
        job = {"id": "job-1", "attempts": 1, "max_attempts": 3, "status": "running"}

        with patch.object(research_job_service, "_database", return_value=service):
            result = research_job_service.record_research_job_failure(
                job,
                RuntimeError("provider secret must not be exposed"),
            )

        updates = query.update.call_args.args[0]
        self.assertEqual(updates["status"], "pending")
        self.assertEqual(updates["error_message"], "任务执行失败，请稍后重试")
        self.assertEqual(updates["result"]["error_code"], "internal_error")
        self.assertEqual(result["status"], "pending")

    def test_permanent_failure_stops_retrying(self):
        service, query = service_with_rows(
            [{"id": "job-1", "status": "failed", "attempts": 1, "max_attempts": 3}]
        )
        job = {"id": "job-1", "attempts": 1, "max_attempts": 3, "status": "running"}

        with patch.object(research_job_service, "_database", return_value=service):
            research_job_service.record_research_job_failure(
                job,
                research_job_service.PermanentResearchJobError("扫描版 PDF 无法解析"),
            )

        updates = query.update.call_args.args[0]
        self.assertEqual(updates["status"], "failed")
        self.assertEqual(updates["error_message"], "扫描版 PDF 无法解析")
        self.assertEqual(updates["result"]["error_code"], "invalid_input")
        self.assertIsNotNone(updates["completed_at"])

    def test_retry_rejects_non_failed_job(self):
        with patch.object(
            research_job_service,
            "get_owned_research_job",
            return_value={"id": "job-1", "status": "running"},
        ):
            with self.assertRaises(HTTPException) as raised:
                research_job_service.retry_owned_research_job("job-1", "user-1")

        self.assertEqual(raised.exception.status_code, 409)

    def test_equivalent_active_job_is_reused(self):
        active = {
            "id": "job-1",
            "status": "running",
            "input": {"direction": "topic", "idempotency_key": "same-key"},
        }
        with (
            patch.object(
                research_job_service,
                "list_owned_research_jobs",
                return_value=[active],
            ),
            patch.object(research_job_service, "create_research_job") as create_job,
        ):
            job, created = research_job_service.create_or_reuse_research_job(
                user_id="user-1",
                job_type="research-decomposition",
                input_data={"direction": "topic"},
                idempotency_key="same-key",
            )

        self.assertEqual(job["id"], "job-1")
        self.assertFalse(created)
        create_job.assert_not_called()

    def test_completed_job_does_not_block_new_generation(self):
        completed = {
            "id": "job-1",
            "status": "succeeded",
            "input": {"direction": "topic", "idempotency_key": "same-key"},
        }
        created_job = {"id": "job-2", "status": "pending"}
        with (
            patch.object(
                research_job_service,
                "list_owned_research_jobs",
                return_value=[completed],
            ),
            patch.object(
                research_job_service,
                "create_research_job",
                return_value=created_job,
            ) as create_job,
        ):
            job, created = research_job_service.create_or_reuse_research_job(
                user_id="user-1",
                job_type="research-decomposition",
                input_data={"direction": "topic"},
                idempotency_key="same-key",
            )

        self.assertEqual(job["id"], "job-2")
        self.assertTrue(created)
        self.assertEqual(
            create_job.call_args.kwargs["input_data"]["idempotency_key"],
            "same-key",
        )


class ResearchJobRouteTests(unittest.TestCase):
    def test_public_job_payload_does_not_expose_internal_input_or_lease(self):
        payload = routes._public_research_job(
            {
                "id": "job-1",
                "status": "running",
                "progress": 35,
                "input": {"file_path": "private/path.pdf"},
                "lease_owner": "worker-secret",
            }
        )

        self.assertEqual(payload["id"], "job-1")
        self.assertNotIn("input", payload)
        self.assertNotIn("lease_owner", payload)

    def test_unknown_job_type_is_permanent_failure(self):
        with self.assertRaises(research_job_service.PermanentResearchJobError):
            routes.process_research_job(
                {
                    "id": "job-1",
                    "user_id": "user-1",
                    "job_type": "unknown",
                }
            )

    def test_problem_decomposition_job_dispatches_to_existing_business_logic(self):
        expected = {"id": "artifact-1", "core_question": "topic"}
        with (
            patch.object(routes, "update_research_job_progress") as progress,
            patch.object(routes, "decompose_research", return_value=expected) as handler,
        ):
            result = routes.process_research_job(
                {
                    "id": "job-1",
                    "user_id": "user-1",
                    "job_type": "research-decomposition",
                    "input": {"direction": "topic"},
                }
            )

        self.assertEqual(result, expected)
        self.assertEqual(handler.call_args.kwargs["user"].id, "user-1")
        self.assertEqual(progress.call_args_list, [call("job-1", 10), call("job-1", 90)])


if __name__ == "__main__":
    unittest.main()

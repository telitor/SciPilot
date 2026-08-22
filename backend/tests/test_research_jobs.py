import asyncio
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from fastapi import HTTPException, UploadFile

from api import routes
from services import research_job_service


def service_with_rows(rows):
    query = MagicMock()
    query.select.return_value = query
    query.insert.return_value = query
    query.update.return_value = query
    query.eq.return_value = query
    query.in_.return_value = query
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

    def test_lease_renewal_is_scoped_to_running_job_and_worker(self):
        service, query = service_with_rows([{"id": "job-1", "status": "running"}])
        with patch.object(research_job_service, "_database", return_value=service):
            renewed = research_job_service.renew_research_job_lease(
                "job-1",
                "worker-1",
                600,
            )

        self.assertTrue(renewed)
        self.assertIn(call("id", "job-1"), query.eq.call_args_list)
        self.assertIn(call("status", "running"), query.eq.call_args_list)
        self.assertIn(call("lease_owner", "worker-1"), query.eq.call_args_list)
        self.assertIn("lease_expires_at", query.update.call_args.args[0])

    def test_transient_failure_is_requeued_before_attempt_limit(self):
        service, query = service_with_rows(
            [{"id": "job-1", "status": "pending", "attempts": 1, "max_attempts": 3}]
        )
        job = {"id": "job-1", "attempts": 1, "max_attempts": 3, "status": "running"}

        with patch.object(research_job_service, "_database", return_value=service):
            result = research_job_service.record_research_job_failure(
                job,
                RuntimeError("provider secret must not be exposed"),
                "worker-1",
            )

        updates = query.update.call_args.args[0]
        self.assertEqual(updates["status"], "pending")
        self.assertEqual(updates["error_message"], "任务执行失败，请稍后重试")
        self.assertEqual(updates["result"]["error_code"], "internal_error")
        self.assertEqual(result["status"], "pending")
        self.assertIn(call("lease_owner", "worker-1"), query.eq.call_args_list)

    def test_permanent_failure_stops_retrying(self):
        service, query = service_with_rows(
            [{"id": "job-1", "status": "failed", "attempts": 1, "max_attempts": 3}]
        )
        job = {"id": "job-1", "attempts": 1, "max_attempts": 3, "status": "running"}

        with patch.object(research_job_service, "_database", return_value=service):
            research_job_service.record_research_job_failure(
                job,
                research_job_service.PermanentResearchJobError("扫描版 PDF 无法解析"),
                "worker-1",
            )

        updates = query.update.call_args.args[0]
        self.assertEqual(updates["status"], "failed")
        self.assertEqual(updates["error_message"], "扫描版 PDF 无法解析")
        self.assertEqual(updates["result"]["error_code"], "invalid_input")
        self.assertIsNotNone(updates["completed_at"])

    def test_stale_worker_cannot_update_progress_or_finish_job(self):
        service, query = service_with_rows([])
        with patch.object(research_job_service, "_database", return_value=service):
            with self.assertRaises(research_job_service.ResearchJobLeaseLost):
                research_job_service.update_research_job_progress(
                    "job-1", 50, "stale-worker"
                )
            with self.assertRaises(research_job_service.ResearchJobLeaseLost):
                research_job_service.complete_research_job(
                    "job-1", {"ok": True}, "stale-worker"
                )

        self.assertIn(call("lease_owner", "stale-worker"), query.eq.call_args_list)

    def test_stale_failure_does_not_fabricate_terminal_state(self):
        service, _query = service_with_rows([])
        job = {"id": "job-1", "attempts": 3, "max_attempts": 3, "status": "running"}
        with patch.object(research_job_service, "_database", return_value=service):
            with self.assertRaises(research_job_service.ResearchJobLeaseLost):
                research_job_service.record_research_job_failure(
                    job,
                    RuntimeError("late failure"),
                    "stale-worker",
                )

    def test_retry_rejects_non_failed_job(self):
        with patch.object(
            research_job_service,
            "get_owned_research_job",
            return_value={"id": "job-1", "status": "running"},
        ):
            with self.assertRaises(HTTPException) as raised:
                research_job_service.retry_owned_research_job("job-1", "user-1")

        self.assertEqual(raised.exception.status_code, 409)

    def test_cancel_owned_job_is_scoped_and_terminal(self):
        cancelled = {"id": "job-1", "user_id": "user-1", "status": "cancelled"}
        service, query = service_with_rows([cancelled])
        with (
            patch.object(
                research_job_service,
                "get_owned_research_job",
                return_value={"id": "job-1", "user_id": "user-1", "status": "running"},
            ),
            patch.object(research_job_service, "_database", return_value=service),
        ):
            result = research_job_service.cancel_owned_research_job("job-1", "user-1")

        updates = query.update.call_args.args[0]
        self.assertEqual(updates["status"], "cancelled")
        self.assertIn(call("user_id", "user-1"), query.eq.call_args_list)
        query.in_.assert_called_once_with("status", ["pending", "running"])
        self.assertEqual(result["status"], "cancelled")

    def test_cancel_rejects_completed_job(self):
        with patch.object(
            research_job_service,
            "get_owned_research_job",
            return_value={"id": "job-1", "status": "succeeded"},
        ):
            with self.assertRaises(HTTPException) as raised:
                research_job_service.cancel_owned_research_job("job-1", "user-1")

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


class ResearchJobWorkerLeaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_keeps_heartbeat_until_processor_finishes(self):
        stop_event = asyncio.Event()
        job = {"id": "job-1", "job_type": "experiment-execution", "attempts": 1}

        def processor(_job):
            stop_event.set()
            return {"ok": True}

        async def heartbeat(**kwargs):
            await kwargs["done_event"].wait()

        with (
            patch.object(research_job_service, "claim_research_job", return_value=job),
            patch.object(research_job_service, "complete_research_job") as complete,
            patch.object(
                research_job_service,
                "_renew_lease_until_done",
                new=AsyncMock(side_effect=heartbeat),
            ) as renew,
        ):
            await research_job_service.run_research_job_worker(
                processor,
                stop_event=stop_event,
            )

        complete.assert_called_once()
        self.assertEqual(complete.call_args.args[:2], ("job-1", {"ok": True}))
        self.assertTrue(complete.call_args.args[2])
        renew.assert_awaited_once()
        self.assertTrue(renew.await_args.kwargs["done_event"].is_set())

    async def test_lost_lease_failure_does_not_trigger_terminal_handler(self):
        stop_event = asyncio.Event()
        job = {"id": "job-1", "job_type": "paper-analysis", "attempts": 3}
        terminal_handler = MagicMock()

        def processor(_job):
            stop_event.set()
            raise RuntimeError("late worker failure")

        async def heartbeat(**kwargs):
            await kwargs["done_event"].wait()

        with (
            patch.object(research_job_service, "claim_research_job", return_value=job),
            patch.object(
                research_job_service,
                "record_research_job_failure",
                side_effect=research_job_service.ResearchJobLeaseLost("lost"),
            ),
            patch.object(
                research_job_service,
                "_renew_lease_until_done",
                new=AsyncMock(side_effect=heartbeat),
            ),
        ):
            await research_job_service.run_research_job_worker(
                processor,
                stop_event=stop_event,
                terminal_failure_handler=terminal_handler,
            )

        terminal_handler.assert_not_called()


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

    def test_stale_experiment_worker_is_fenced_before_run_state_changes(self):
        job = {
            "id": "job-1",
            "user_id": "user-1",
            "lease_owner": "stale-worker",
            "job_type": "experiment-execution",
            "input": {"experiment_run_id": "run-1"},
        }
        run = {
            "id": "run-1",
            "user_id": "user-1",
            "execution_mode": "sandboxed-docker",
            "execution_job_id": "job-1",
            "status": "planned",
            "code_artifact_id": "artifact-1",
        }
        artifact = {
            "id": "artifact-1",
            "artifact_type": "code-reproduction",
            "content": {"repo_url": "https://github.com/example/repo.git"},
        }
        with (
            patch.object(routes, "_owned_experiment_run", return_value=run),
            patch.object(routes, "require_owned_row", return_value=artifact),
            patch.object(
                routes,
                "update_research_job_progress",
                side_effect=research_job_service.ResearchJobLeaseLost("lost"),
            ) as progress,
            patch.object(routes, "database") as database,
            patch.object(routes, "execute_repository_run") as execute,
        ):
            with self.assertRaises(research_job_service.ResearchJobLeaseLost):
                routes.process_research_job(job)

        progress.assert_called_once_with("job-1", 10, "stale-worker")
        database.assert_not_called()
        execute.assert_not_called()

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
                    "lease_owner": "worker-1",
                    "job_type": "research-decomposition",
                    "input": {"direction": "topic"},
                }
            )

        self.assertEqual(result, expected)
        self.assertEqual(handler.call_args.kwargs["user"].id, "user-1")
        self.assertEqual(
            progress.call_args_list,
            [call("job-1", 10, "worker-1"), call("job-1", 90, "worker-1")],
        )

    def test_paper_knowledge_sync_runs_as_durable_job(self):
        paper = {
            "id": "paper-1",
            "user_id": "user-1",
            "file_path": "user-1/paper-1/paper.pdf",
            "file_name": "paper.pdf",
            "mime_type": "application/pdf",
            "checksum_sha256": "abc",
            "project_id": None,
        }
        database = MagicMock()
        database.storage.from_.return_value.download.return_value = b"%PDF-content"
        mapping = {"id": "mapping-1", "status": "pending", "file_name": "paper.pdf"}
        completed = {"status": "uploaded", "attempt_count": 1}
        with (
            patch.object(routes, "database", return_value=database),
            patch.object(routes, "require_owned_row", return_value=paper),
            patch.object(routes, "_paper_knowledge_mapping", return_value=(True, mapping)),
            patch.object(
                routes,
                "_complete_paper_knowledge_sync",
                return_value=completed,
            ) as complete,
            patch.object(routes, "update_research_job_progress") as progress,
        ):
            result = routes.process_research_job(
                {
                    "id": "job-1",
                    "user_id": "user-1",
                    "paper_id": "paper-1",
                    "lease_owner": "worker-1",
                    "job_type": "paper-knowledge-sync",
                    "input": {"paper_id": "paper-1"},
                }
            )

        self.assertEqual(result["knowledge_sync"]["status"], "uploaded")
        self.assertTrue(complete.call_args.kwargs["raise_on_failure"])
        self.assertEqual(
            progress.call_args_list,
            [
                call("job-1", 20, "worker-1"),
                call("job-1", 50, "worker-1"),
                call("job-1", 90, "worker-1"),
            ],
        )


class PaperUploadReuseTests(unittest.IsolatedAsyncioTestCase):
    def test_reusable_lookup_is_scoped_to_owner_project_and_completed_report(self):
        paper_query = MagicMock()
        report_query = MagicMock()
        for query in (paper_query, report_query):
            query.select.return_value = query
            query.eq.return_value = query
            query.is_.return_value = query
            query.order.return_value = query
            query.limit.return_value = query
        paper_query.execute.return_value = SimpleNamespace(
            data=[{"id": "paper-1", "title": "Existing paper"}]
        )
        report_query.execute.return_value = SimpleNamespace(data=[{"id": "report-1"}])
        service = MagicMock()
        service.table.side_effect = [paper_query, report_query]

        with patch.object(routes, "database", return_value=service):
            result = routes._find_reusable_completed_paper(
                user_id="user-1",
                project_id="project-1",
                checksum_sha256="checksum-1",
            )

        self.assertEqual(result["id"], "paper-1")
        self.assertIn(call("user_id", "user-1"), paper_query.eq.call_args_list)
        self.assertIn(call("project_id", "project-1"), paper_query.eq.call_args_list)
        self.assertIn(
            call("checksum_sha256", "checksum-1"), paper_query.eq.call_args_list
        )
        self.assertIn(call("status", "completed"), report_query.eq.call_args_list)

    async def test_completed_report_is_reused_without_creating_agent_job(self):
        reusable = {"id": "paper-1", "title": "Existing paper"}
        upload = UploadFile(filename="paper.pdf", file=BytesIO(b"%PDF-demo"))
        with (
            patch.object(routes, "_validated_project_id", return_value="project-1"),
            patch.object(
                routes,
                "_find_reusable_completed_paper",
                return_value=reusable,
            ) as find_reusable,
            patch.object(routes, "record_activity"),
            patch.object(routes, "create_research_job") as create_job,
        ):
            result = await routes.upload_paper_async(
                file=upload,
                project_id="project-1",
                user=SimpleNamespace(id="user-1"),
            )

        self.assertTrue(result["reused"])
        self.assertEqual(result["paper_id"], "paper-1")
        self.assertIsNone(result["job_id"])
        find_reusable.assert_called_once()
        create_job.assert_not_called()


if __name__ == "__main__":
    unittest.main()

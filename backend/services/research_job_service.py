"""Durable Supabase-backed jobs for long-running research work."""

import asyncio
import logging
import os
import socket
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from services.supabase_service import SupabaseConfigurationError, get_supabase_client

logger = logging.getLogger(__name__)

JOB_COLUMNS = (
    "id,user_id,project_id,paper_id,job_type,status,progress,input,result,"
    "error_message,attempts,max_attempts,available_at,lease_owner,"
    "lease_expires_at,started_at,completed_at,created_at,updated_at"
)


class PermanentResearchJobError(RuntimeError):
    """An invalid job input that should not consume additional retries."""


class ResearchJobLeaseLost(RuntimeError):
    """The worker no longer owns a claimed job and must not mutate it."""


def _database():
    return get_supabase_client()


def _first(result: Any) -> dict[str, Any] | None:
    return result.data[0] if getattr(result, "data", None) else None


def create_research_job(
    *,
    user_id: str,
    job_type: str,
    input_data: dict[str, Any],
    project_id: str | None = None,
    paper_id: str | None = None,
    max_attempts: int = 3,
) -> dict[str, Any]:
    result = (
        _database()
        .table("research_jobs")
        .insert(
            {
                "user_id": user_id,
                "project_id": project_id,
                "paper_id": paper_id,
                "job_type": job_type,
                "status": "pending",
                "progress": 0,
                "input": input_data,
                "max_attempts": max_attempts,
            }
        )
        .execute()
    )
    job = _first(result)
    if not job:
        raise RuntimeError("Unable to create research job")
    return job


def create_or_reuse_research_job(
    *,
    user_id: str,
    job_type: str,
    input_data: dict[str, Any],
    idempotency_key: str,
    project_id: str | None = None,
    paper_id: str | None = None,
    max_attempts: int = 3,
) -> tuple[dict[str, Any], bool]:
    """Reuse an equivalent active job, or create a new durable job."""

    stored_input = {**input_data, "idempotency_key": idempotency_key}
    for job in list_owned_research_jobs(
        user_id,
        job_type=job_type,
        project_id=project_id,
        limit=20,
    ):
        if job.get("status") not in {"pending", "running"}:
            continue
        current_input = job.get("input")
        if (
            isinstance(current_input, dict)
            and current_input.get("idempotency_key") == idempotency_key
        ):
            return job, False

    return (
        create_research_job(
            user_id=user_id,
            job_type=job_type,
            input_data=stored_input,
            project_id=project_id,
            paper_id=paper_id,
            max_attempts=max_attempts,
        ),
        True,
    )


def get_owned_research_job(job_id: str, user_id: str) -> dict[str, Any]:
    result = (
        _database()
        .table("research_jobs")
        .select(JOB_COLUMNS)
        .eq("id", job_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    job = _first(result)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


def list_owned_research_jobs(
    user_id: str,
    *,
    job_type: str | None = None,
    project_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    query = (
        _database()
        .table("research_jobs")
        .select(JOB_COLUMNS)
        .eq("user_id", user_id)
    )
    if job_type:
        query = query.eq("job_type", job_type)
    if project_id:
        query = query.eq("project_id", project_id)
    result = query.order("created_at", desc=True).limit(limit).execute()
    return result.data or []


def retry_owned_research_job(job_id: str, user_id: str) -> dict[str, Any]:
    current = get_owned_research_job(job_id, user_id)
    if current.get("status") != "failed":
        raise HTTPException(status_code=409, detail="只有失败任务可以重试")
    result = (
        _database()
        .table("research_jobs")
        .update(
            {
                "status": "pending",
                "progress": 0,
                "error_message": None,
                "result": {},
                "attempts": 0,
                "available_at": datetime.now(timezone.utc).isoformat(),
                "lease_owner": None,
                "lease_expires_at": None,
                "started_at": None,
                "completed_at": None,
            }
        )
        .eq("id", job_id)
        .eq("user_id", user_id)
        .eq("status", "failed")
        .execute()
    )
    job = _first(result)
    if not job:
        raise HTTPException(status_code=409, detail="任务状态已变化，请刷新后重试")
    return job


def cancel_owned_research_job(job_id: str, user_id: str) -> dict[str, Any]:
    current = get_owned_research_job(job_id, user_id)
    if current.get("status") == "cancelled":
        return current
    if current.get("status") not in {"pending", "running"}:
        raise HTTPException(status_code=409, detail="只有等待中或执行中的任务可以取消")
    now = datetime.now(timezone.utc).isoformat()
    result = (
        _database()
        .table("research_jobs")
        .update(
            {
                "status": "cancelled",
                "error_message": None,
                "lease_owner": None,
                "lease_expires_at": None,
                "completed_at": now,
            }
        )
        .eq("id", job_id)
        .eq("user_id", user_id)
        .in_("status", ["pending", "running"])
        .execute()
    )
    job = _first(result)
    if not job:
        raise HTTPException(status_code=409, detail="任务状态已变化，请刷新后重试")
    return job


def claim_research_job(worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
    result = _database().rpc(
        "claim_research_job",
        {
            "p_worker_id": worker_id,
            "p_lease_seconds": lease_seconds,
        },
    ).execute()
    return _first(result)


def renew_research_job_lease(
    job_id: str,
    worker_id: str,
    lease_seconds: int,
) -> bool:
    """Extend an owned running lease so long external/GPU work is not reclaimed."""

    bounded_seconds = max(30, min(int(lease_seconds), 900))
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=bounded_seconds)
    ).isoformat()
    result = (
        _database()
        .table("research_jobs")
        .update({"lease_expires_at": expires_at})
        .eq("id", job_id)
        .eq("status", "running")
        .eq("lease_owner", worker_id)
        .execute()
    )
    return bool(getattr(result, "data", None))


def update_research_job_progress(
    job_id: str,
    progress: int,
    lease_owner: str,
) -> None:
    result = (
        _database()
        .table("research_jobs")
        .update({"progress": max(0, min(99, progress))})
        .eq("id", job_id)
        .eq("status", "running")
        .eq("lease_owner", lease_owner)
        .execute()
    )
    if not _first(result):
        raise ResearchJobLeaseLost(f"Research job lease lost: {job_id}")


def complete_research_job(
    job_id: str,
    result_data: dict[str, Any],
    lease_owner: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    result = (
        _database()
        .table("research_jobs")
        .update(
            {
                "status": "succeeded",
                "progress": 100,
                "result": result_data,
                "error_message": None,
                "lease_owner": None,
                "lease_expires_at": None,
                "completed_at": now,
            }
        )
        .eq("id", job_id)
        .eq("status", "running")
        .eq("lease_owner", lease_owner)
        .execute()
    )
    if not _first(result):
        raise ResearchJobLeaseLost(f"Research job lease lost: {job_id}")


def _safe_error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPException) and isinstance(exc.detail, str):
        return exc.detail[:1000]
    if isinstance(exc, PermanentResearchJobError):
        return str(exc)[:1000]
    return "任务执行失败，请稍后重试"


def _error_code(exc: Exception) -> str:
    if isinstance(exc, PermanentResearchJobError):
        return "invalid_input"
    if isinstance(exc, HTTPException):
        if exc.status_code in {408, 504}:
            return "timeout"
        if exc.status_code >= 500:
            return "upstream_unavailable"
    if "timeout" in str(exc).lower():
        return "timeout"
    return "internal_error"


def record_research_job_failure(
    job: dict[str, Any],
    exc: Exception,
    lease_owner: str,
) -> dict[str, Any]:
    attempts = int(job.get("attempts") or 0)
    max_attempts = int(job.get("max_attempts") or 3)
    retryable = not isinstance(exc, PermanentResearchJobError)
    should_retry = retryable and attempts < max_attempts
    now = datetime.now(timezone.utc)
    delay_seconds = min(15 * (2 ** max(attempts - 1, 0)), 120)
    updates: dict[str, Any] = {
        "status": "pending" if should_retry else "failed",
        "error_message": _safe_error_message(exc),
        "result": {"error_code": _error_code(exc)},
        "lease_owner": None,
        "lease_expires_at": None,
        "available_at": (now + timedelta(seconds=delay_seconds)).isoformat(),
    }
    if not should_retry:
        updates["completed_at"] = now.isoformat()
    result = (
        _database()
        .table("research_jobs")
        .update(updates)
        .eq("id", job["id"])
        .eq("status", "running")
        .eq("lease_owner", lease_owner)
        .execute()
    )
    failed_job = _first(result)
    if not failed_job:
        raise ResearchJobLeaseLost(f"Research job lease lost: {job['id']}")
    return failed_job


async def _wait_or_stop(stop_event: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def _renew_lease_until_done(
    *,
    job_id: str,
    worker_id: str,
    lease_seconds: int,
    done_event: asyncio.Event,
    lease_lost_event: asyncio.Event,
) -> None:
    """Renew a job lease in the background until its processor finishes."""

    interval = max(15.0, min(lease_seconds / 3, 120.0))
    while not done_event.is_set():
        try:
            await asyncio.wait_for(done_event.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
        try:
            renewed = await asyncio.to_thread(
                renew_research_job_lease,
                job_id,
                worker_id,
                lease_seconds,
            )
        except Exception as exc:
            logger.warning(
                "Research job lease renewal failed job_id=%s error=%s",
                job_id,
                type(exc).__name__,
            )
            continue
        if not renewed:
            logger.error("Research job lease ownership was lost job_id=%s", job_id)
            lease_lost_event.set()
            return


async def run_research_job_worker(
    processor: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    stop_event: asyncio.Event,
    terminal_failure_handler: Callable[[dict[str, Any], Exception], None] | None = None,
) -> None:
    worker_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    lease_seconds = max(120, min(int(os.getenv("RESEARCH_JOB_LEASE_SECONDS", "600")), 900))
    poll_seconds = max(1.0, float(os.getenv("RESEARCH_JOB_POLL_SECONDS", "2")))
    logger.info("Research job worker started worker_id=%s", worker_id)

    while not stop_event.is_set():
        try:
            job = await asyncio.to_thread(
                claim_research_job,
                worker_id,
                lease_seconds,
            )
        except SupabaseConfigurationError:
            logger.warning("Research job worker is waiting for Supabase configuration")
            await _wait_or_stop(stop_event, 10)
            continue
        except Exception as exc:
            logger.warning("Research job claim failed: %s", type(exc).__name__)
            await _wait_or_stop(stop_event, 5)
            continue

        if not job:
            await _wait_or_stop(stop_event, poll_seconds)
            continue

        job_id = str(job["id"])
        processing_done = asyncio.Event()
        lease_lost = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            _renew_lease_until_done(
                job_id=job_id,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                done_event=processing_done,
                lease_lost_event=lease_lost,
            )
        )
        try:
            result_data = await asyncio.to_thread(processor, job)
            if lease_lost.is_set():
                raise ResearchJobLeaseLost(f"Research job lease lost: {job_id}")
            await asyncio.to_thread(
                complete_research_job,
                job_id,
                result_data,
                worker_id,
            )
        except ResearchJobLeaseLost:
            logger.warning("Research job lease lost; stale result discarded job_id=%s", job_id)
        except Exception as exc:
            logger.warning(
                "Research job failed job_type=%s attempt=%s error=%s",
                job.get("job_type"),
                job.get("attempts"),
                type(exc).__name__,
            )
            try:
                failed_job = await asyncio.to_thread(
                    record_research_job_failure,
                    job,
                    exc,
                    worker_id,
                )
            except ResearchJobLeaseLost:
                logger.warning(
                    "Research job lease lost; stale failure discarded job_id=%s",
                    job_id,
                )
                continue
            if (
                failed_job.get("status") == "failed"
                and terminal_failure_handler is not None
            ):
                await asyncio.to_thread(terminal_failure_handler, failed_job, exc)
        finally:
            processing_done.set()
            await heartbeat_task

    logger.info("Research job worker stopped worker_id=%s", worker_id)

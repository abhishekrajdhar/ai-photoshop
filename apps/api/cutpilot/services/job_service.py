"""Job lifecycle helpers used by the API (async) and workers (sync)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from cutpilot.core.logging import get_logger
from cutpilot.db.models import Job
from cutpilot.services.events import publish_async, sync_publisher

log = get_logger(__name__)

JOB_TYPES = {
    "UPLOAD_PROCESSING",
    "PROXY_GENERATION",
    "TRANSCRIPTION",
    "SCENE_DETECTION",
    "AUDIO_ANALYSIS",
    "VISION_ANALYSIS",
    "CONTENT_ANALYSIS",
    "EDIT_PLANNING",
    "HIGHLIGHT_DETECTION",
    "SHORT_GENERATION",
    "THUMBNAIL_GENERATION",
    "REFRAME_TRACKING",
    "RENDERING",
    "EXPORT",
}


async def create_job(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID | None,
    job_type: str,
    meta: dict[str, Any] | None = None,
    max_retries: int = 2,
) -> Job:
    if job_type not in JOB_TYPES:
        raise ValueError(f"unknown job type {job_type}")
    job = Job(
        user_id=user_id,
        project_id=project_id,
        type=job_type,
        status="QUEUED",
        meta=meta or {},
        queued_at=datetime.now(UTC),
        max_retries=max_retries,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    await publish_async("job.queued", _job_event(job), project_id=project_id, user_id=user_id)
    return job


async def list_jobs(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    limit: int = 50,
    active_only: bool = False,
) -> list[Job]:
    q = select(Job).where(Job.user_id == user_id)
    if project_id is not None:
        q = q.where(Job.project_id == project_id)
    if active_only:
        q = q.where(Job.status.in_(["QUEUED", "RUNNING"]))
    rows = (await db.execute(q.order_by(Job.created_at.desc()).limit(limit))).scalars().all()
    return list(rows)


async def cancel_job(db: AsyncSession, job: Job) -> Job:
    if job.status in ("QUEUED", "RUNNING"):
        job.status = "CANCELLED"
        job.completed_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(job)
        if job.celery_task_id:
            try:
                from cutpilot.workers.celery_app import celery_app

                celery_app.control.revoke(job.celery_task_id, terminate=True)
            except Exception as exc:
                log.warning("job_revoke_failed", job_id=str(job.id), error=str(exc))
        await publish_async(
            "job.cancelled", _job_event(job), project_id=job.project_id, user_id=job.user_id
        )
    return job


def _job_event(job: Job) -> dict[str, Any]:
    return {
        "job_id": str(job.id),
        "project_id": str(job.project_id) if job.project_id else None,
        "type": job.type,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "result": job.result,
        "meta": job.meta,
    }


# ── synchronous helpers for workers ──────────────────────────────────────────


class JobContext:
    """Worker-side handle for updating a job's progress and emitting events."""

    def __init__(self, session: Session, job: Job):
        self.session = session
        self.job = job

    @property
    def id(self) -> uuid.UUID:
        return self.job.id

    def start(self, celery_task_id: str | None = None) -> None:
        self.job.status = "RUNNING"
        self.job.started_at = datetime.now(UTC)
        self.job.celery_task_id = celery_task_id
        self.job.error = None
        self.session.commit()
        self._emit("job.started")

    def progress(self, value: float, message: str = "", event: str | None = None) -> None:
        self.job.progress = max(0.0, min(1.0, value))
        if message:
            self.job.message = message[:500]
        self.session.commit()
        self._emit(event or f"{self.job.type.lower()}.progress")

    def complete(self, result: dict[str, Any] | None = None, event: str | None = None) -> None:
        self.job.status = "COMPLETED"
        self.job.progress = 1.0
        self.job.completed_at = datetime.now(UTC)
        if result:
            self.job.result = result
        self.session.commit()
        self._emit(event or f"{self.job.type.lower()}.completed")

    def fail(self, error: str, *, will_retry: bool = False) -> None:
        self.job.error = error[:4000]
        if will_retry:
            self.job.retry_count += 1
            self.job.status = "QUEUED"
            self.job.message = f"Retrying ({self.job.retry_count}/{self.job.max_retries})"
        else:
            self.job.status = "FAILED"
            self.job.completed_at = datetime.now(UTC)
        self.session.commit()
        self._emit("job.retrying" if will_retry else "job.failed")

    def is_cancelled(self) -> bool:
        self.session.refresh(self.job)
        return self.job.status == "CANCELLED"

    def _emit(self, event: str) -> None:
        sync_publisher.publish(
            event, _job_event(self.job), project_id=self.job.project_id, user_id=self.job.user_id
        )

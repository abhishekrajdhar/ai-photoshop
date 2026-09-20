"""Shared worker plumbing: DB session, job context, retries."""

from __future__ import annotations

import functools
import uuid
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

from celery import Task

from cutpilot.core.errors import AppError
from cutpilot.core.logging import get_logger
from cutpilot.db.models import Job
from cutpilot.db.session import get_sync_session_factory
from cutpilot.services.job_service import JobContext

log = get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


class JobCancelled(Exception):
    pass


def job_task(fn: Callable[..., dict[str, Any] | None]) -> Callable[..., dict[str, Any] | None]:
    """Wrap a Celery task body `fn(ctx: JobContext, session, **kwargs)` with job lifecycle handling.

    The Celery task must be declared with `bind=True` and take `job_id` as first argument.
    """

    @functools.wraps(fn)
    def wrapper(self: Task, job_id: str, **kwargs: Any) -> dict[str, Any] | None:
        session_factory = get_sync_session_factory()
        with session_factory() as session:
            job = session.get(Job, uuid.UUID(job_id))
            if job is None:
                log.error("job_missing", job_id=job_id)
                return None
            if job.status == "CANCELLED":
                return None
            ctx = JobContext(session, job)
            ctx.start(celery_task_id=getattr(self.request, "id", None))
            try:
                result = fn(ctx, session, **kwargs)
                if ctx.is_cancelled():
                    return None
                ctx.complete(result or {})
                return result
            except JobCancelled:
                return None
            except Exception as exc:
                session.rollback()
                session.refresh(job)
                will_retry = job.retry_count < job.max_retries and not isinstance(exc, AppError)
                message = str(exc) or exc.__class__.__name__
                log.exception("job_failed", job_id=job_id, type=job.type, will_retry=will_retry)
                ctx.fail(message, will_retry=will_retry)
                if will_retry:
                    raise self.retry(
                        exc=exc,
                        countdown=min(60 * (2**job.retry_count), 600),
                        max_retries=job.max_retries,
                    ) from exc
                return None

    return wrapper

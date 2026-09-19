from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from cutpilot.api.deps import CurrentUser, DBSession, rate_limit
from cutpilot.core.errors import NotFoundError
from cutpilot.db.models import Job
from cutpilot.schemas.job import JobOut
from cutpilot.services import job_service

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(rate_limit)])


async def _owned_job(job_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Job:
    job = await db.get(Job, job_id)
    if job is None or job.user_id != user.id:
        raise NotFoundError("Job not found")
    return job


@router.get("", response_model=list[JobOut])
async def list_jobs(
    user: CurrentUser,
    db: DBSession,
    project_id: uuid.UUID | None = None,
    active_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[JobOut]:
    jobs = await job_service.list_jobs(
        db, user_id=user.id, project_id=project_id, limit=limit, active_only=active_only
    )
    return [JobOut.model_validate(j) for j in jobs]


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job: Job = Depends(_owned_job)) -> JobOut:
    return JobOut.model_validate(job)


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(db: DBSession, job: Job = Depends(_owned_job)) -> JobOut:
    return JobOut.model_validate(await job_service.cancel_job(db, job))

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from cutpilot.api.deps import DBSession, OwnedProject, rate_limit
from cutpilot.core.errors import NotFoundError
from cutpilot.db.models import Timeline, TimelineVersion
from cutpilot.schemas.common import OkResponse
from cutpilot.schemas.timeline import (
    ApplyOperationsRequest,
    ApplyOperationsResponse,
    SaveTimelineRequest,
    TimelineCreateRequest,
    TimelineOut,
    TimelineStateOut,
    TimelineVersionOut,
    VersionCompareOut,
)
from cutpilot.services import timeline_service as ts
from cutpilot.services.events import publish_async
from cutpilot.timeline.model import TimelineDocument

router = APIRouter(
    prefix="/projects/{project_id}", tags=["timeline"], dependencies=[Depends(rate_limit)]
)


async def _state(
    db: DBSession, timeline: Timeline, version: TimelineVersion | None = None
) -> TimelineStateOut:
    version = version or await ts.current_version(db, timeline)
    counts = await ts.operation_counts(db, [version.id])
    vout = TimelineVersionOut.model_validate(version)
    vout.operation_count = counts.get(version.id, 0)
    return TimelineStateOut(
        timeline=TimelineOut.model_validate(timeline),
        version=vout,
        document=version.document,
        can_undo=version.parent_version_id is not None,
        can_redo=await ts.has_redo(db, timeline, version),
    )


@router.get("/timelines", response_model=list[TimelineOut])
async def list_timelines(project: OwnedProject, db: DBSession) -> list[TimelineOut]:
    return [TimelineOut.model_validate(t) for t in await ts.list_timelines(db, project)]


@router.post("/timelines", response_model=TimelineStateOut, status_code=201)
async def create_timeline(
    body: TimelineCreateRequest, project: OwnedProject, db: DBSession
) -> TimelineStateOut:
    if body.from_version_id:
        src = await db.get(TimelineVersion, body.from_version_id)
        if src is None:
            raise NotFoundError("Version not found")
        src_tl = await db.get(Timeline, src.timeline_id)
        if src_tl is None or src_tl.project_id != project.id:
            raise NotFoundError("Version not found")
        doc = ts.load_document(src)
    else:
        doc = TimelineDocument.empty(timeline_id="pending", name=body.name)
    timeline = await ts.create_timeline(
        db, project=project, name=body.name, kind=body.kind, document=doc
    )
    return await _state(db, timeline)


@router.get("/timeline", response_model=TimelineStateOut)
async def get_timeline(
    project: OwnedProject, db: DBSession, timeline_id: uuid.UUID | None = None
) -> TimelineStateOut:
    timeline = await ts.get_timeline(db, project, timeline_id)
    return await _state(db, timeline)


@router.put("/timeline", response_model=TimelineStateOut)
async def save_timeline(
    body: SaveTimelineRequest,
    project: OwnedProject,
    db: DBSession,
    timeline_id: uuid.UUID | None = None,
) -> TimelineStateOut:
    timeline = await ts.get_timeline(db, project, timeline_id)
    version = await ts.save_document(
        db, project=project, timeline=timeline, document=body.document, label=body.label
    )
    await publish_async(
        "timeline.updated",
        {"timeline_id": str(timeline.id), "version_id": str(version.id)},
        project_id=project.id,
    )
    return await _state(db, timeline, version)


@router.post("/timeline/operations", response_model=ApplyOperationsResponse)
async def apply_operations(
    body: ApplyOperationsRequest,
    project: OwnedProject,
    db: DBSession,
    timeline_id: uuid.UUID | None = None,
) -> ApplyOperationsResponse:
    timeline = await ts.get_timeline(db, project, timeline_id)
    old, new, result = await ts.apply_ops_to_timeline(
        db,
        project=project,
        timeline=timeline,
        operations=body.operations,
        label=body.label,
        source=body.source,
    )
    await publish_async(
        "timeline.updated",
        {"timeline_id": str(timeline.id), "version_id": str(new.id)},
        project_id=project.id,
    )
    return ApplyOperationsResponse(
        state=await _state(db, timeline, new),
        applied=result.applied,
        rejected=[
            {"operation": op.model_dump(mode="json"), "reason": why} for op, why in result.rejected
        ],
        duration_before=old.duration,
        duration_after=new.duration,
    )


@router.get("/timeline/versions", response_model=list[TimelineVersionOut])
async def list_versions(
    project: OwnedProject, db: DBSession, timeline_id: uuid.UUID | None = None
) -> list[TimelineVersionOut]:
    timeline = await ts.get_timeline(db, project, timeline_id)
    versions = await ts.list_versions(db, timeline)
    counts = await ts.operation_counts(db, [v.id for v in versions])
    out = []
    for v in versions:
        item = TimelineVersionOut.model_validate(v)
        item.operation_count = counts.get(v.id, 0)
        out.append(item)
    return out


@router.get("/timeline/versions/{version_id}", response_model=TimelineStateOut)
async def get_version(
    version_id: uuid.UUID, project: OwnedProject, db: DBSession
) -> TimelineStateOut:
    version = await db.get(TimelineVersion, version_id)
    if version is None:
        raise NotFoundError("Version not found")
    timeline = await ts.get_timeline(db, project, version.timeline_id)
    return await _state(db, timeline, version)


@router.post("/timeline/versions/{version_id}/restore", response_model=TimelineStateOut)
async def restore_version(
    version_id: uuid.UUID, project: OwnedProject, db: DBSession
) -> TimelineStateOut:
    version = await db.get(TimelineVersion, version_id)
    if version is None:
        raise NotFoundError("Version not found")
    timeline = await ts.get_timeline(db, project, version.timeline_id)
    new = await ts.restore_version(db, project=project, timeline=timeline, version=version)
    return await _state(db, timeline, new)


@router.get("/timeline/versions/{version_id}/compare/{other_id}", response_model=VersionCompareOut)
async def compare_versions(
    version_id: uuid.UUID, other_id: uuid.UUID, project: OwnedProject, db: DBSession
) -> VersionCompareOut:
    a = await db.get(TimelineVersion, version_id)
    b = await db.get(TimelineVersion, other_id)
    if a is None or b is None:
        raise NotFoundError("Version not found")
    await ts.get_timeline(db, project, a.timeline_id)
    await ts.get_timeline(db, project, b.timeline_id)
    diff = ts.compare_documents(ts.load_document(a), ts.load_document(b))
    return VersionCompareOut(
        a=TimelineVersionOut.model_validate(a), b=TimelineVersionOut.model_validate(b), **diff
    )


@router.post("/timeline/undo", response_model=TimelineStateOut)
async def undo(
    project: OwnedProject, db: DBSession, timeline_id: uuid.UUID | None = None
) -> TimelineStateOut:
    timeline = await ts.get_timeline(db, project, timeline_id)
    version = await ts.undo(db, timeline)
    return await _state(db, timeline, version)


@router.post("/timeline/redo", response_model=TimelineStateOut)
async def redo(
    project: OwnedProject, db: DBSession, timeline_id: uuid.UUID | None = None
) -> TimelineStateOut:
    timeline = await ts.get_timeline(db, project, timeline_id)
    version = await ts.redo(db, timeline)
    return await _state(db, timeline, version)


@router.delete("/timelines/{timeline_id}", response_model=OkResponse)
async def delete_timeline(
    timeline_id: uuid.UUID, project: OwnedProject, db: DBSession
) -> OkResponse:
    timeline = await ts.get_timeline(db, project, timeline_id)
    if timeline.is_primary:
        raise NotFoundError("The primary timeline cannot be deleted")
    await db.delete(timeline)
    await db.commit()
    return OkResponse()

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from cutpilot.api.deps import CurrentUser, DBSession, OwnedProject, ai_rate_limit, rate_limit
from cutpilot.schemas.analysis import AnalyzeResponse
from cutpilot.schemas.creator import (
    BrollMatchOut,
    BrollPlaceRequest,
    BrollResolveResult,
    HighlightOut,
    HighlightRequest,
    MulticamSyncOut,
    MulticamSyncRequest,
    SequenceSettingsUpdate,
    ShortsRequest,
    ThumbnailsOut,
)
from cutpilot.schemas.job import JobOut
from cutpilot.services import creator_service as svc
from cutpilot.services.analysis_service import primary_source_asset
from cutpilot.services.events import publish_async

router = APIRouter(
    prefix="/projects/{project_id}", tags=["creator"], dependencies=[Depends(rate_limit)]
)


@router.get("/highlights", response_model=list[HighlightOut])
async def list_highlights(project: OwnedProject, db: DBSession) -> list[HighlightOut]:
    return [HighlightOut.model_validate(h) for h in await svc.list_highlights(db, project)]


@router.post("/highlights", response_model=AnalyzeResponse, dependencies=[Depends(ai_rate_limit)])
async def detect_highlights(
    body: HighlightRequest, project: OwnedProject, user: CurrentUser, db: DBSession
) -> AnalyzeResponse:
    asset = await primary_source_asset(db, project, body.asset_id)
    job = await svc.start_highlights(
        db,
        project=project,
        user=user,
        asset=asset,
        count=body.count,
        min_seconds=body.min_seconds,
        max_seconds=body.max_seconds,
        platform=body.platform,
    )
    return AnalyzeResponse(jobs=[JobOut.model_validate(job).model_dump(mode="json")])


@router.post("/shorts", response_model=AnalyzeResponse, dependencies=[Depends(ai_rate_limit)])
async def generate_shorts(
    body: ShortsRequest, project: OwnedProject, user: CurrentUser, db: DBSession
) -> AnalyzeResponse:
    job = await svc.start_short_generation(
        db,
        project=project,
        user=user,
        count=body.count,
        duration=body.duration,
        platform=body.platform,
        asset_id=body.asset_id,
        highlight_ids=body.highlight_ids,
        caption_preset=body.caption_preset,
        reframe=body.reframe,
        auto_render=body.auto_render,
        render_preset=body.render_preset,
    )
    return AnalyzeResponse(jobs=[JobOut.model_validate(job).model_dump(mode="json")])


@router.post("/thumbnails", response_model=AnalyzeResponse)
async def generate_thumbnails(
    project: OwnedProject, user: CurrentUser, db: DBSession, asset_id: str | None = None
) -> AnalyzeResponse:
    import uuid as _uuid

    asset = await primary_source_asset(db, project, _uuid.UUID(asset_id) if asset_id else None)
    job = await svc.start_thumbnails(db, project=project, user=user, asset=asset)
    return AnalyzeResponse(jobs=[JobOut.model_validate(job).model_dump(mode="json")])


@router.get("/thumbnails", response_model=ThumbnailsOut)
async def list_thumbnails(project: OwnedProject, db: DBSession) -> ThumbnailsOut:
    return ThumbnailsOut(**await svc.thumbnails(db, project))


@router.post("/reframe/track", response_model=AnalyzeResponse)
async def track_reframe(
    project: OwnedProject, user: CurrentUser, db: DBSession, asset_id: str | None = None
) -> AnalyzeResponse:
    import uuid as _uuid

    asset = await primary_source_asset(db, project, _uuid.UUID(asset_id) if asset_id else None)
    job = await svc.start_reframe_tracking(db, project=project, user=user, asset=asset)
    return AnalyzeResponse(jobs=[JobOut.model_validate(job).model_dump(mode="json")])


@router.get("/broll/search", response_model=list[BrollMatchOut])
async def search_broll(
    project: OwnedProject, db: DBSession, q: str = Query(min_length=1, max_length=200)
) -> list[BrollMatchOut]:
    return [
        BrollMatchOut(
            asset_id=m.asset_id,
            filename=m.filename,
            score=m.score,
            duration=m.duration,
            media_type=m.media_type,
            reason=m.reason,
        )
        for m in await svc.search_broll(db, project, q)
    ]


@router.post("/broll/resolve", response_model=BrollResolveResult)
async def resolve_broll(
    project: OwnedProject, db: DBSession, timeline_id: str | None = None
) -> BrollResolveResult:
    import uuid as _uuid

    result = await svc.resolve_broll_markers(
        db, project=project, timeline_id=_uuid.UUID(timeline_id) if timeline_id else None
    )
    if result["state"]:
        await publish_async("timeline.updated", {"reason": "broll"}, project_id=project.id)
    return BrollResolveResult(**result)


@router.post("/broll/place")
async def place_broll(
    body: BrollPlaceRequest, project: OwnedProject, db: DBSession
) -> dict[str, object]:
    result = await svc.place_broll(
        db,
        project=project,
        timeline_id=body.timeline_id,
        marker_id=body.marker_id,
        asset_id=body.asset_id,
        duration=body.duration,
    )
    await publish_async("timeline.updated", {"reason": "broll"}, project_id=project.id)
    return result


@router.post("/multicam/sync", response_model=MulticamSyncOut)
async def multicam_sync(
    body: MulticamSyncRequest, project: OwnedProject, db: DBSession
) -> MulticamSyncOut:
    result = await svc.multicam_sync(
        db,
        project=project,
        reference_asset_id=body.reference_asset_id,
        asset_ids=body.asset_ids,
        place=body.place_on_timeline,
        timeline_id=body.timeline_id,
    )
    if result["state"]:
        await publish_async("timeline.updated", {"reason": "multicam"}, project_id=project.id)
    return MulticamSyncOut(**result)


@router.patch("/sequence")
async def update_sequence(
    body: SequenceSettingsUpdate, project: OwnedProject, db: DBSession
) -> dict[str, object]:
    result = await svc.update_sequence_settings(
        db,
        project=project,
        timeline_id=body.timeline_id,
        caption_style=body.caption_style,
        audio=body.audio,
        aspect_ratio=body.aspect_ratio,
        reframe_mode=body.reframe_mode,
    )
    await publish_async("timeline.updated", {"reason": "sequence_settings"}, project_id=project.id)
    return result

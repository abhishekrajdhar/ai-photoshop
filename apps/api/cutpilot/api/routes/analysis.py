from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from cutpilot.ai.router import provider_status
from cutpilot.ai.transcription import transcription_available
from cutpilot.api.deps import CurrentUser, DBSession, OwnedProject, ai_rate_limit, rate_limit
from cutpilot.core.config import get_settings
from cutpilot.core.errors import NotFoundError
from cutpilot.schemas.analysis import (
    AIStatusOut,
    AnalysisResultOut,
    AnalyzeRequest,
    AnalyzeResponse,
    SceneOut,
    SegmentTextUpdate,
    SpeakerOut,
    SpeakerUpdate,
    TranscriptOut,
    TranscriptSegmentOut,
    TranscriptWordOut,
    WordUpdate,
)
from cutpilot.schemas.job import JobOut
from cutpilot.services import analysis_service as svc
from cutpilot.services import pipeline_service
from cutpilot.services.events import publish_async
from cutpilot.storage import get_storage

router = APIRouter(
    prefix="/projects/{project_id}", tags=["analysis"], dependencies=[Depends(rate_limit)]
)


@router.post("/transcribe", response_model=AnalyzeResponse, dependencies=[Depends(ai_rate_limit)])
async def transcribe(
    project: OwnedProject, user: CurrentUser, db: DBSession, body: AnalyzeRequest | None = None
) -> AnalyzeResponse:
    body = body or AnalyzeRequest(steps=["transcription"])
    asset = await svc.primary_source_asset(db, project, body.asset_id)
    jobs = await pipeline_service.run_analysis(
        db,
        project=project,
        user=user,
        asset=asset,
        steps=["transcription"],
        language=body.language,
        force=body.force,
    )
    return AnalyzeResponse(jobs=[JobOut.model_validate(j).model_dump(mode="json") for j in jobs])


@router.post("/analyze", response_model=AnalyzeResponse, dependencies=[Depends(ai_rate_limit)])
async def analyze(
    body: AnalyzeRequest, project: OwnedProject, user: CurrentUser, db: DBSession
) -> AnalyzeResponse:
    asset = await svc.primary_source_asset(db, project, body.asset_id)
    jobs = await pipeline_service.run_analysis(
        db,
        project=project,
        user=user,
        asset=asset,
        steps=list(body.steps),
        language=body.language,
        force=body.force,
    )
    return AnalyzeResponse(jobs=[JobOut.model_validate(j).model_dump(mode="json") for j in jobs])


@router.get("/transcript", response_model=TranscriptOut | None)
async def get_transcript(
    project: OwnedProject, db: DBSession, asset_id: uuid.UUID | None = None
) -> TranscriptOut | None:
    t = await svc.get_current_transcript(db, project, asset_id)
    return svc.serialize_transcript(t) if t else None


@router.get("/transcripts", response_model=list[TranscriptOut])
async def list_transcripts(project: OwnedProject, db: DBSession) -> list[TranscriptOut]:
    return [svc.serialize_transcript(t) for t in await svc.list_transcripts(db, project)]


@router.patch("/transcript/segments/{segment_id}", response_model=TranscriptSegmentOut)
async def update_segment(
    segment_id: uuid.UUID, body: SegmentTextUpdate, project: OwnedProject, db: DBSession
) -> TranscriptSegmentOut:
    seg = await svc.update_segment_text(db, project, segment_id, body.text)
    await publish_async("transcript.updated", {"segment_id": str(seg.id)}, project_id=project.id)
    return TranscriptSegmentOut.model_validate(seg)


@router.patch("/transcript/words/{word_id}", response_model=TranscriptWordOut)
async def update_word(
    word_id: uuid.UUID, body: WordUpdate, project: OwnedProject, db: DBSession
) -> TranscriptWordOut:
    word = await svc.update_word(db, project, word_id, text=body.text, is_filler=body.is_filler)
    await publish_async("transcript.updated", {"word_id": str(word.id)}, project_id=project.id)
    return TranscriptWordOut.model_validate(word)


@router.patch("/transcript/speakers/{speaker_id}", response_model=SpeakerOut)
async def rename_speaker(
    speaker_id: uuid.UUID, body: SpeakerUpdate, project: OwnedProject, db: DBSession
) -> SpeakerOut:
    spk = await svc.rename_speaker(
        db, project, speaker_id, display_name=body.display_name, color=body.color
    )
    await publish_async("transcript.updated", {"speaker_id": str(spk.id)}, project_id=project.id)
    return SpeakerOut.model_validate(spk)


@router.get("/scenes", response_model=list[SceneOut])
async def list_scenes(
    project: OwnedProject, db: DBSession, asset_id: uuid.UUID | None = None
) -> list[SceneOut]:
    return await svc.list_scenes(db, project, asset_id)


@router.get("/scenes/{scene_id}/thumbnail")
async def scene_thumbnail(
    scene_id: uuid.UUID, project: OwnedProject, db: DBSession, request: Request
) -> Response:
    scene = await svc.get_scene(db, project, scene_id)
    if not scene.thumbnail_key:
        raise NotFoundError("No thumbnail")
    storage = get_storage()
    signed = storage.signed_url(scene.thumbnail_key)
    if signed:
        return RedirectResponse(signed, status_code=307)
    path = storage.local_path(scene.thumbnail_key)
    if path is None:
        raise NotFoundError("No thumbnail")
    return FileResponse(
        path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"}
    )


@router.get("/analysis", response_model=list[AnalysisResultOut])
async def list_analysis(
    project: OwnedProject,
    db: DBSession,
    kind: list[str] | None = Query(default=None),
    asset_id: uuid.UUID | None = None,
) -> list[AnalysisResultOut]:
    return await svc.list_results(db, project, kinds=kind, asset_id=asset_id)


@router.get("/ai-status", response_model=AIStatusOut)
async def ai_status(project: OwnedProject) -> AIStatusOut:
    s = get_settings()
    status = provider_status()
    return AIStatusOut(
        **status,
        transcription={
            "provider": s.transcription_provider
            if s.local_transcription_enabled
            else ("openai" if s.openai_api_key else "faster_whisper"),
            "local_enabled": s.local_transcription_enabled,
            "diarization": s.local_diarization_enabled,
            "available": transcription_available(),
        },
    )

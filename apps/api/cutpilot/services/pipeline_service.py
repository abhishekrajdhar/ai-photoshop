"""Creates analysis jobs and dispatches them to Celery with dependency ordering."""

from __future__ import annotations

from typing import Any

from celery import chain
from sqlalchemy.ext.asyncio import AsyncSession

from cutpilot.db.models import Job, MediaAsset, Project, User
from cutpilot.services import job_service

STEP_TO_JOB = {
    "transcription": "TRANSCRIPTION",
    "audio": "AUDIO_ANALYSIS",
    "scenes": "SCENE_DETECTION",
    "content": "CONTENT_ANALYSIS",
    "vision": "VISION_ANALYSIS",
    "highlights": "HIGHLIGHT_DETECTION",
    "thumbnails": "THUMBNAIL_GENERATION",
}


async def run_analysis(
    db: AsyncSession,
    *,
    project: Project,
    user: User,
    asset: MediaAsset,
    steps: list[str],
    language: str | None,
    force: bool,
) -> list[Job]:
    from cutpilot.workers.tasks import analysis as tasks

    jobs: dict[str, Job] = {}
    for step in steps:
        if step not in STEP_TO_JOB:
            continue
        if step in ("scenes", "vision", "thumbnails") and asset.media_type != "video":
            continue
        jobs[step] = await job_service.create_job(
            db,
            user_id=user.id,
            project_id=project.id,
            job_type=STEP_TO_JOB[step],
            meta={"asset_id": str(asset.id), "step": step, "filename": asset.filename},
        )

    common: dict[str, Any] = {"asset_id": str(asset.id), "force": force}
    sig = {}
    if "transcription" in jobs:
        sig["transcription"] = tasks.transcribe.si(
            job_id=str(jobs["transcription"].id), language=language, **common
        ).set(queue="ai")
    if "audio" in jobs:
        sig["audio"] = tasks.audio_analysis.si(job_id=str(jobs["audio"].id), **common).set(
            queue="ai"
        )
    if "scenes" in jobs:
        sig["scenes"] = tasks.scene_detection.si(job_id=str(jobs["scenes"].id), **common).set(
            queue="ai"
        )
    if "content" in jobs:
        sig["content"] = tasks.content_analysis.si(job_id=str(jobs["content"].id), **common).set(
            queue="ai"
        )
    if "vision" in jobs:
        sig["vision"] = tasks.vision_analysis.si(job_id=str(jobs["vision"].id), **common).set(
            queue="ai"
        )
    if "highlights" in jobs:
        from cutpilot.workers.tasks import ai as ai_tasks

        sig["highlights"] = ai_tasks.detect_highlights.si(
            job_id=str(jobs["highlights"].id), **common
        ).set(queue="ai")
    if "thumbnails" in jobs:
        from cutpilot.workers.tasks import ai as ai_tasks

        sig["thumbnails"] = ai_tasks.generate_thumbnails.si(
            job_id=str(jobs["thumbnails"].id), **common
        ).set(queue="ai")

    # Dependency chains: transcription → content → highlights ; scenes → vision → thumbnails ; audio standalone.
    text_chain = [sig[k] for k in ("transcription", "content", "highlights") if k in sig]
    visual_chain = [sig[k] for k in ("scenes", "vision", "thumbnails") if k in sig]
    for group in (text_chain, visual_chain):
        if group:
            (chain(*group) if len(group) > 1 else group[0]).apply_async()
    if "audio" in sig:
        sig["audio"].apply_async()
    return list(jobs.values())

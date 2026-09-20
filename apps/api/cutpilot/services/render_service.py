"""Render / export orchestration (API side)."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cutpilot.core.errors import NotFoundError, ValidationFailed
from cutpilot.db.models import Export, Job, Project, Render, User
from cutpilot.render.presets import PRESETS, resolve_preset
from cutpilot.schemas.render import ExportOut, PresetOut, RenderOut
from cutpilot.services import job_service
from cutpilot.services import timeline_service as ts

PLATFORM_PRESET = {
    "youtube_shorts": "youtube_shorts",
    "instagram_reels": "instagram_reel",
    "tiktok": "tiktok",
    "youtube": "youtube_1080p",
    "podcast": "podcast",
    "linkedin": "youtube_1080p",
    "twitter": "youtube_1080p",
    "generic": "youtube_1080p",
}


def preset_for_platform(platform: str | None) -> str:
    return PLATFORM_PRESET.get((platform or "").lower(), "youtube_shorts")


def start_render_sync(
    session,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    timeline_id: uuid.UUID,
    preset: str,
    filename: str,
    settings: dict[str, Any] | None = None,
) -> tuple[Render, Job]:  # type: ignore[no-untyped-def]
    """Worker-side render kickoff (e.g. auto-render generated Shorts)."""
    from cutpilot.db.models import Timeline
    from cutpilot.services.job_service import create_job_sync
    from cutpilot.services.timeline_sync import current_version
    from cutpilot.workers.tasks.render import render_timeline

    timeline = session.get(Timeline, timeline_id)
    version = current_version(session, timeline) if timeline else None
    if timeline is None or version is None:
        raise ValidationFailed("Timeline not found")
    resolved = resolve_preset(preset if preset in PRESETS else "youtube_shorts", settings or {})
    render = Render(
        project_id=project_id,
        timeline_version_id=version.id,
        kind="final",
        status="QUEUED",
        preset=resolved.id,
        settings={**resolved.to_dict(), "filename": safe_name(filename, f"{timeline.name}.mp4")},
    )
    session.add(render)
    session.commit()
    job = create_job_sync(
        session,
        user_id=user_id,
        project_id=project_id,
        job_type="RENDERING",
        meta={
            "render_id": str(render.id),
            "timeline_id": str(timeline.id),
            "version": version.version,
            "preset": resolved.id,
            "kind": "final",
            "short": True,
        },
        max_retries=1,
    )
    render.job_id = job.id
    session.commit()
    task = render_timeline.apply_async(
        kwargs={"job_id": str(job.id), "render_id": str(render.id)}, queue="render"
    )
    job.celery_task_id = task.id
    session.commit()
    return render, job


def list_presets() -> list[PresetOut]:
    return [PresetOut(**p.to_dict()) for p in PRESETS.values() if p.id != "preview"]


def safe_name(name: str | None, default: str) -> str:
    raw = (name or default).strip()
    raw = re.sub(r"[^\w.\- ]+", "_", raw)[:150]
    return raw or default


def serialize_render(r: Render) -> RenderOut:
    out = RenderOut.model_validate(r)
    if r.output_asset_id:
        out.download_url = f"/api/assets/{r.output_asset_id}/download"
        out.stream_url = f"/api/assets/{r.output_asset_id}/stream"
    return out


def serialize_export(e: Export) -> ExportOut:
    out = ExportOut.model_validate(e)
    if e.output_asset_id:
        out.download_url = f"/api/assets/{e.output_asset_id}/download"
    return out


async def start_render(
    db: AsyncSession,
    *,
    project: Project,
    user: User,
    timeline_id: uuid.UUID | None,
    preset: str,
    settings: dict[str, Any],
    kind: str = "final",
) -> tuple[Render, Job]:
    from cutpilot.workers.tasks.render import render_timeline

    timeline = await ts.get_timeline(db, project, timeline_id)
    version = await ts.current_version(db, timeline)
    if version.duration <= 0:
        raise ValidationFailed("The timeline is empty — add clips before rendering")
    doc = ts.load_document(version)
    if not any(c.asset_id for t in doc.tracks if t.kind in ("video", "audio") for c in t.clips):
        raise ValidationFailed("The timeline has no video or audio clips to render")
    if preset not in PRESETS:
        raise ValidationFailed(f"Unknown preset {preset}")
    resolved = resolve_preset("preview" if kind == "preview" else preset, settings)
    render = Render(
        project_id=project.id,
        timeline_version_id=version.id,
        kind=kind,
        status="QUEUED",
        preset=preset,
        settings={
            **resolved.to_dict(),
            "filename": safe_name(settings.get("filename"), f"{project.name}-{timeline.name}.mp4"),
        },
    )
    db.add(render)
    await db.commit()
    await db.refresh(render)
    job = await job_service.create_job(
        db,
        user_id=user.id,
        project_id=project.id,
        job_type="RENDERING",
        meta={
            "render_id": str(render.id),
            "timeline_id": str(timeline.id),
            "version": version.version,
            "preset": preset,
            "kind": kind,
        },
        max_retries=1,
    )
    render.job_id = job.id
    await db.commit()
    task = render_timeline.apply_async(
        kwargs={"job_id": str(job.id), "render_id": str(render.id)}, queue="render"
    )
    job.celery_task_id = task.id
    await db.commit()
    await db.refresh(render)
    return render, job


async def start_export(
    db: AsyncSession,
    *,
    project: Project,
    user: User,
    timeline_id: uuid.UUID | None,
    fmt: str,
    preset: str,
    filename: str | None,
    settings: dict[str, Any],
) -> tuple[Export, Job]:
    from cutpilot.workers.tasks.render import export_timeline

    timeline = await ts.get_timeline(db, project, timeline_id)
    version = await ts.current_version(db, timeline)
    if version.duration <= 0:
        raise ValidationFailed("The timeline is empty")
    ext = "xml" if fmt == "fcpxml" else fmt
    name = safe_name(filename, f"{project.name}-{timeline.name}.{ext}")
    if not name.lower().endswith(f".{ext}"):
        name = f"{name}.{ext}"
    export = Export(
        project_id=project.id,
        timeline_version_id=version.id,
        format=fmt,
        preset=preset,
        filename=name,
        status="QUEUED",
        settings=settings,
    )
    db.add(export)
    await db.commit()
    await db.refresh(export)
    job = await job_service.create_job(
        db,
        user_id=user.id,
        project_id=project.id,
        job_type="EXPORT",
        meta={"export_id": str(export.id), "format": fmt, "timeline_id": str(timeline.id)},
        max_retries=1,
    )
    export.job_id = job.id
    await db.commit()
    task = export_timeline.apply_async(
        kwargs={"job_id": str(job.id), "export_id": str(export.id)}, queue="render"
    )
    job.celery_task_id = task.id
    await db.commit()
    await db.refresh(export)
    return export, job


async def list_renders(db: AsyncSession, project: Project) -> list[Render]:
    return list(
        (
            await db.execute(
                select(Render)
                .where(Render.project_id == project.id)
                .order_by(Render.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )


async def list_exports(db: AsyncSession, project: Project) -> list[Export]:
    return list(
        (
            await db.execute(
                select(Export)
                .where(Export.project_id == project.id)
                .order_by(Export.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )


async def get_render(db: AsyncSession, project: Project, render_id: uuid.UUID) -> Render:
    r = await db.get(Render, render_id)
    if r is None or r.project_id != project.id:
        raise NotFoundError("Render not found")
    return r


async def get_export(db: AsyncSession, export_id: uuid.UUID) -> Export:
    e = await db.get(Export, export_id)
    if e is None:
        raise NotFoundError("Export not found")
    return e

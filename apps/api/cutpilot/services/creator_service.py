"""Creator features orchestration: highlights, Shorts, thumbnails, B-roll, multicam, sequence settings."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cutpilot.core.errors import NotFoundError, ValidationFailed
from cutpilot.db.models import (
    AnalysisResult,
    Highlight,
    Job,
    MediaAsset,
    MediaMetadata,
    Project,
    User,
)
from cutpilot.render.captions import PRESETS as CAPTION_PRESETS
from cutpilot.services import job_service
from cutpilot.services import timeline_service as ts
from cutpilot.services.broll_service import BrollMatch, get_broll_providers
from cutpilot.timeline.engine import _aspect_dims, add_source_clip
from cutpilot.timeline.model import Clip, TimelineDocument


async def list_highlights(db: AsyncSession, project: Project) -> list[Highlight]:
    return list(
        (
            await db.execute(
                select(Highlight)
                .where(Highlight.project_id == project.id)
                .order_by(Highlight.score.desc())
            )
        )
        .scalars()
        .all()
    )


async def start_highlights(
    db: AsyncSession,
    *,
    project: Project,
    user: User,
    asset: MediaAsset,
    count: int,
    min_seconds: float,
    max_seconds: float,
    platform: str | None,
) -> Job:
    from cutpilot.workers.tasks.ai import detect_highlights_task

    job = await job_service.create_job(
        db,
        user_id=user.id,
        project_id=project.id,
        job_type="HIGHLIGHT_DETECTION",
        meta={"asset_id": str(asset.id), "count": count},
        max_retries=0,
    )
    task = detect_highlights_task.apply_async(
        kwargs={
            "job_id": str(job.id),
            "asset_id": str(asset.id),
            "count": count,
            "min_len": min_seconds,
            "max_len": max_seconds,
            "platform": platform,
        },
        queue="ai",
    )
    job.celery_task_id = task.id
    await db.commit()
    return job


async def start_short_generation(
    db: AsyncSession,
    *,
    project: Project,
    user: User,
    count: int,
    duration: int,
    platform: str | None,
    asset_id: uuid.UUID | None = None,
    highlight_ids: list[uuid.UUID] | None = None,
    caption_preset: str = "bold",
    reframe: bool = True,
) -> Job:
    from cutpilot.services.analysis_service import primary_source_asset
    from cutpilot.workers.tasks.ai import generate_shorts_task

    asset = await primary_source_asset(db, project, asset_id)
    if caption_preset not in CAPTION_PRESETS:
        raise ValidationFailed("Unknown caption preset")
    job = await job_service.create_job(
        db,
        user_id=user.id,
        project_id=project.id,
        job_type="SHORT_GENERATION",
        meta={"asset_id": str(asset.id), "count": count, "duration": duration},
        max_retries=0,
    )
    task = generate_shorts_task.apply_async(
        kwargs={
            "job_id": str(job.id),
            "asset_id": str(asset.id),
            "count": count,
            "duration": duration,
            "platform": platform,
            "highlight_ids": [str(h) for h in highlight_ids] if highlight_ids else None,
            "caption_preset": caption_preset,
            "reframe": reframe,
        },
        queue="ai",
    )
    job.celery_task_id = task.id
    await db.commit()
    return job


async def start_thumbnails(
    db: AsyncSession, *, project: Project, user: User, asset: MediaAsset
) -> Job:
    from cutpilot.workers.tasks.ai import generate_thumbnails

    job = await job_service.create_job(
        db,
        user_id=user.id,
        project_id=project.id,
        job_type="THUMBNAIL_GENERATION",
        meta={"asset_id": str(asset.id)},
        max_retries=0,
    )
    task = generate_thumbnails.apply_async(
        kwargs={"job_id": str(job.id), "asset_id": str(asset.id)}, queue="ai"
    )
    job.celery_task_id = task.id
    await db.commit()
    return job


async def start_reframe_tracking(
    db: AsyncSession, *, project: Project, user: User, asset: MediaAsset
) -> Job:
    from cutpilot.workers.tasks.ai import track_reframe

    job = await job_service.create_job(
        db,
        user_id=user.id,
        project_id=project.id,
        job_type="REFRAME_TRACKING",
        meta={"asset_id": str(asset.id)},
        max_retries=0,
    )
    task = track_reframe.apply_async(
        kwargs={"job_id": str(job.id), "asset_id": str(asset.id)}, queue="ai"
    )
    job.celery_task_id = task.id
    await db.commit()
    return job


async def thumbnails(db: AsyncSession, project: Project) -> dict[str, Any]:
    row = (
        (
            await db.execute(
                select(AnalysisResult)
                .where(AnalysisResult.project_id == project.id, AnalysisResult.kind == "thumbnails")
                .order_by(AnalysisResult.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        return {"source_asset_id": None, "candidates": []}
    cands = []
    for c in row.data.get("candidates", []):
        cands.append({**c, "asset_id": c["asset_id"], "url": f"/api/assets/{c['asset_id']}/stream"})
    return {"source_asset_id": row.asset_id, "candidates": cands}


# ── B-roll ──────────────────────────────────────────────────────────────────


async def search_broll(db: AsyncSession, project: Project, query: str) -> list[BrollMatch]:
    out: list[BrollMatch] = []
    for provider in get_broll_providers():
        out.extend(await provider.search(db, project.id, query))
    return sorted(out, key=lambda m: -m.score)


async def resolve_broll_markers(
    db: AsyncSession, *, project: Project, timeline_id: uuid.UUID | None, min_score: float = 0.34
) -> dict[str, Any]:
    timeline = await ts.get_timeline(db, project, timeline_id)
    version = await ts.current_version(db, timeline)
    doc = ts.load_document(version)
    placed: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for marker in [m for m in doc.markers if m.kind == "broll_suggestion"]:
        query = str(marker.meta.get("query") or marker.label.replace("B-roll:", "")).strip()
        matches = await search_broll(db, project, query)
        best = matches[0] if matches and matches[0].score >= min_score else None
        if best is None:
            unresolved.append(
                {
                    "marker_id": marker.id,
                    "time": marker.time,
                    "query": query,
                    "candidates": [m.__dict__ for m in matches[:3]],
                }
            )
            continue
        duration = float(marker.meta.get("duration", 4.0))
        _place(
            doc, marker.id, best.asset_id, best.filename, best.media_type, duration, best.duration
        )
        placed.append(
            {
                "marker_id": marker.id,
                "time": marker.time,
                "query": query,
                "asset_id": str(best.asset_id),
                "score": best.score,
            }
        )
    state = None
    if placed:
        new_version = await ts.commit_version(
            db,
            project=project,
            timeline=timeline,
            document=doc,
            label=f"Placed {len(placed)} B-roll clip(s)",
            source="system",
            parent=version,
        )
        state = {"version_id": str(new_version.id), "version": new_version.version}
    return {"placed": placed, "unresolved": unresolved, "state": state}


async def place_broll(
    db: AsyncSession,
    *,
    project: Project,
    timeline_id: uuid.UUID | None,
    marker_id: str,
    asset_id: uuid.UUID,
    duration: float | None,
) -> dict[str, Any]:
    timeline = await ts.get_timeline(db, project, timeline_id)
    version = await ts.current_version(db, timeline)
    doc = ts.load_document(version)
    asset = await db.get(MediaAsset, asset_id)
    if asset is None or asset.project_id != project.id:
        raise NotFoundError("Asset not found")
    meta = (
        await db.execute(select(MediaMetadata).where(MediaMetadata.asset_id == asset.id))
    ).scalar_one_or_none()
    marker = next((m for m in doc.markers if m.id == marker_id), None)
    if marker is None:
        raise NotFoundError("Marker not found")
    _place(
        doc,
        marker.id,
        asset.id,
        asset.filename,
        asset.media_type,
        duration or float(marker.meta.get("duration", 4.0)),
        meta.duration if meta else None,
    )
    new_version = await ts.commit_version(
        db,
        project=project,
        timeline=timeline,
        document=doc,
        label=f"Placed B-roll {asset.filename}",
        source="user",
        parent=version,
    )
    return {
        "version_id": str(new_version.id),
        "version": new_version.version,
        "document": new_version.document,
    }


def _place(
    doc: TimelineDocument,
    marker_id: str,
    asset_id: uuid.UUID,
    filename: str,
    media_type: str,
    duration: float,
    media_duration: float | None,
) -> None:
    marker = next(m for m in doc.markers if m.id == marker_id)
    video_tracks = doc.tracks_of_kind("video")
    track = video_tracks[1] if len(video_tracks) > 1 else video_tracks[0]
    dur = duration if media_type == "image" else min(duration, media_duration or duration)
    clip = Clip(
        kind="image" if media_type == "image" else "broll",
        name=filename,
        asset_id=str(asset_id),
        timeline_start=round(marker.time, 6),
        duration=round(dur, 6),
        source_in=0.0,
        source_out=round(dur, 6),
        muted=True,
        meta={
            "query": marker.meta.get("query"),
            "reason": marker.meta.get("reason"),
            "from_marker": marker_id,
        },
    )
    track.clips = [
        c
        for c in track.clips
        if not (c.timeline_start < clip.timeline_end and c.timeline_end > clip.timeline_start)
    ]
    track.clips.append(clip)
    doc.markers = [m for m in doc.markers if m.id != marker_id]
    doc.sort()


# ── Multicam ────────────────────────────────────────────────────────────────


async def multicam_sync(
    db: AsyncSession,
    *,
    project: Project,
    reference_asset_id: uuid.UUID,
    asset_ids: list[uuid.UUID],
    place: bool,
    timeline_id: uuid.UUID | None,
) -> dict[str, Any]:
    from cutpilot.analysis.audio_sync import estimate_offset
    from cutpilot.storage import get_storage

    storage = get_storage()

    async def audio_key(aid: uuid.UUID) -> tuple[MediaAsset, str]:
        asset = await db.get(MediaAsset, aid)
        if asset is None or asset.project_id != project.id:
            raise NotFoundError("Asset not found")
        audio = (
            (
                await db.execute(
                    select(MediaAsset).where(
                        MediaAsset.parent_asset_id == asset.id, MediaAsset.kind == "audio"
                    )
                )
            )
            .scalars()
            .first()
        )
        if audio is None:
            raise ValidationFailed(f"{asset.filename} has no extracted audio")
        return asset, audio.storage_key

    ref_asset, ref_key = await audio_key(reference_asset_id)
    offsets: list[dict[str, Any]] = []
    with storage.as_local_file(ref_key, suffix=".wav") as ref_path:
        for aid in asset_ids:
            if aid == reference_asset_id:
                continue
            asset, key = await audio_key(aid)
            with storage.as_local_file(key, suffix=".wav") as other_path:
                res = estimate_offset(ref_path, other_path)
            asset.role = asset.role or f"cam_{len(offsets) + 2}"
            asset.extra = {**asset.extra, "multicam": {"reference": str(reference_asset_id), **res}}
            offsets.append(
                {"asset_id": str(aid), "filename": asset.filename, "role": asset.role, **res}
            )
    ref_asset.role = ref_asset.role or "cam_1"
    await db.commit()
    state = None
    if place:
        timeline = await ts.get_timeline(db, project, timeline_id)
        version = await ts.current_version(db, timeline)
        doc = ts.load_document(version)
        ref_clips = doc.clips_for_asset(str(reference_asset_id))
        base_start = ref_clips[0][1].timeline_start if ref_clips else 0.0
        video_tracks = doc.tracks_of_kind("video")
        for o in offsets:
            asset = await db.get(MediaAsset, uuid.UUID(o["asset_id"]))
            meta = (
                (
                    await db.execute(
                        select(MediaMetadata).where(MediaMetadata.asset_id == asset.id)
                    )
                ).scalar_one_or_none()
                if asset
                else None
            )
            if asset is None or meta is None or not meta.duration:
                continue
            # Other angle starts at base_start + offset (positive offset = other lags reference)
            start = base_start + float(o["offset"])
            source_in = max(0.0, -start)
            start = max(0.0, start)
            track = video_tracks[min(len(video_tracks) - 1, 1)]
            duration = meta.duration - source_in
            track.clips.append(
                Clip(
                    kind="video",
                    name=f"{asset.role}: {asset.filename}",
                    asset_id=str(asset.id),
                    timeline_start=round(start, 6),
                    duration=round(duration, 6),
                    source_in=round(source_in, 6),
                    source_out=round(source_in + duration, 6),
                    muted=True,
                    meta={"multicam_role": asset.role},
                )
            )
        doc.sort()
        new_version = await ts.commit_version(
            db,
            project=project,
            timeline=timeline,
            document=doc,
            label="Added synced camera angles",
            source="system",
            parent=version,
        )
        state = {"version_id": str(new_version.id), "version": new_version.version}
    return {"reference_asset_id": reference_asset_id, "offsets": offsets, "state": state}


# ── Sequence settings ───────────────────────────────────────────────────────


async def update_sequence_settings(
    db: AsyncSession,
    *,
    project: Project,
    timeline_id: uuid.UUID | None,
    caption_style: dict[str, Any] | None,
    audio: dict[str, Any] | None,
    aspect_ratio: str | None,
    reframe_mode: str | None,
) -> dict[str, Any]:
    timeline = await ts.get_timeline(db, project, timeline_id)
    version = await ts.current_version(db, timeline)
    doc = ts.load_document(version)
    label_parts: list[str] = []
    if caption_style:
        merged = {
            **doc.settings.caption_style.model_dump(),
            **{k: v for k, v in caption_style.items() if v is not None},
        }
        preset = caption_style.get("preset")
        if preset in CAPTION_PRESETS:
            merged.update(CAPTION_PRESETS[preset])
            merged["preset"] = preset
        doc.settings.caption_style = doc.settings.caption_style.model_validate(merged)
        label_parts.append("caption style")
    if audio is not None:
        doc.settings.audio = {**doc.settings.audio, **audio}
        label_parts.append("audio processing")
    if aspect_ratio or reframe_mode:
        if reframe_mode == "off":
            doc.settings.reframe = None
            src = doc.primary_video_track().sorted_clips()
            if src:
                w, h = src[0].meta.get("width"), src[0].meta.get("height")
                if w and h:
                    doc.settings.width, doc.settings.height = int(w), int(h)
            label_parts.append("reframe off")
        else:
            aspect = aspect_ratio or doc.settings.aspect_ratio
            doc.settings.aspect_ratio = aspect
            doc.settings.width, doc.settings.height = _aspect_dims(
                aspect, doc.settings.width, doc.settings.height
            )
            doc.settings.reframe = {
                "mode": reframe_mode or (doc.settings.reframe or {}).get("mode", "track"),
                "keyframes": (doc.settings.reframe or {}).get("keyframes", []),
            }
            label_parts.append(f"{aspect} {doc.settings.reframe['mode']}")
    new_version = await ts.commit_version(
        db,
        project=project,
        timeline=timeline,
        document=doc,
        label="Sequence settings: " + ", ".join(label_parts or ["updated"]),
        source="user",
        parent=version,
    )
    return {
        "version_id": str(new_version.id),
        "version": new_version.version,
        "document": new_version.document,
    }


def add_clip_to_doc(doc: TimelineDocument, asset: MediaAsset, meta: MediaMetadata) -> None:
    add_source_clip(
        doc,
        asset_id=str(asset.id),
        name=asset.filename,
        duration=float(meta.duration or 0.0),
        has_video=asset.media_type == "video",
        has_audio=bool(meta.audio_codec),
        fps=meta.fps,
        width=meta.width,
        height=meta.height,
    )

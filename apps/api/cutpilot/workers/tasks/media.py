"""Media pipeline tasks: upload processing → metadata, thumbnail, proxy, audio, waveform."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cutpilot.core.config import get_settings
from cutpilot.core.errors import ValidationFailed
from cutpilot.core.logging import get_logger
from cutpilot.db.models import MediaAsset, MediaMetadata, UploadSession
from cutpilot.media.ffmpeg import MediaInfo, ffprobe
from cutpilot.media.hashing import sha256_file
from cutpilot.media.proxy import (
    compute_waveform_peaks,
    dumps_waveform,
    extract_audio,
    make_audio_proxy,
    make_image_thumbnail,
    make_proxy,
    make_thumbnail,
)
from cutpilot.media.validation import validate_file_contents
from cutpilot.services.events import sync_publisher
from cutpilot.services.job_service import JobContext
from cutpilot.services.timeline_sync import commit_version, current_version, primary_timeline
from cutpilot.storage import build_key, get_storage
from cutpilot.timeline.engine import add_source_clip
from cutpilot.timeline.model import TimelineDocument
from cutpilot.workers.base import JobCancelled, job_task
from cutpilot.workers.celery_app import celery_app

log = get_logger(__name__)


def _work_dir(job_id: uuid.UUID) -> Path:
    d = Path(get_settings().work_dir) / "jobs" / str(job_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _add_derived(
    session: Session,
    parent: MediaAsset,
    *,
    kind: str,
    media_type: str,
    filename: str,
    key: str,
    mime: str,
    size: int,
    extra: dict[str, Any] | None = None,
) -> MediaAsset:
    asset = MediaAsset(
        project_id=parent.project_id,
        parent_asset_id=parent.id,
        kind=kind,
        media_type=media_type,
        filename=filename,
        storage_key=key,
        mime_type=mime,
        size_bytes=size,
        status="ready",
        content_hash=parent.content_hash,
        extra=extra or {},
    )
    session.add(asset)
    session.flush()
    return asset


def _save_metadata(session: Session, asset: MediaAsset, info: MediaInfo) -> None:
    w, h = info.display_size
    meta = session.execute(
        select(MediaMetadata).where(MediaMetadata.asset_id == asset.id)
    ).scalar_one_or_none()
    if meta is None:
        meta = MediaMetadata(asset_id=asset.id)
        session.add(meta)
    meta.container = info.container
    meta.video_codec = info.video_codec
    meta.audio_codec = info.audio_codec
    meta.width, meta.height = w, h
    meta.fps = info.fps
    meta.duration = info.duration
    meta.bitrate = info.bitrate
    meta.audio_channels = info.audio_channels
    meta.sample_rate = info.sample_rate
    meta.rotation = info.rotation
    meta.raw = {
        "format": info.raw.get("format", {}),
        "streams": info.raw.get("streams", []),
        "has_video": info.has_video,
        "has_audio": info.has_audio,
    }
    session.flush()


def _assemble_upload(session: Session, upload: UploadSession, ctx: JobContext) -> Path:
    """Concatenate received chunks into one file inside the job work dir."""
    chunk_dir = Path(get_settings().work_dir) / "uploads" / str(upload.id)
    dest = _work_dir(ctx.id) / f"upload{Path(upload.filename).suffix.lower()}"
    with dest.open("wb") as out:
        for i in range(upload.total_chunks):
            part = chunk_dir / f"chunk_{i:06d}"
            if not part.is_file():
                raise ValidationFailed(f"Upload is missing chunk {i}")
            with part.open("rb") as fh:
                shutil.copyfileobj(fh, out, 8 * 1024 * 1024)
            if i % 8 == 0:
                ctx.progress(
                    0.02 + 0.08 * (i + 1) / upload.total_chunks,
                    f"Assembling upload ({i + 1}/{upload.total_chunks})",
                )
                if ctx.is_cancelled():
                    raise JobCancelled()
    actual = dest.stat().st_size
    if actual != upload.size_bytes:
        raise ValidationFailed(
            f"Assembled size {actual} does not match declared size {upload.size_bytes}"
        )
    shutil.rmtree(chunk_dir, ignore_errors=True)
    return dest


def _add_to_primary_timeline(session: Session, asset: MediaAsset, info: MediaInfo) -> None:
    """Append a newly processed original (video/audio) to the project's primary timeline."""
    timeline = primary_timeline(session, asset.project_id)
    if timeline is None:
        return
    version = current_version(session, timeline)
    doc = (
        TimelineDocument.model_validate(version.document)
        if version
        else TimelineDocument.empty(timeline_id=str(timeline.id))
    )
    if str(asset.id) in doc.asset_ids():
        return
    w, h = info.display_size
    add_source_clip(
        doc,
        asset_id=str(asset.id),
        name=asset.filename,
        duration=info.duration,
        has_video=info.has_video,
        has_audio=info.has_audio,
        fps=info.fps,
        width=w,
        height=h,
    )
    commit_version(
        session, timeline, doc, label=f"Added {asset.filename}", source="system", parent=version
    )
    sync_publisher.publish(
        "timeline.updated",
        {"timeline_id": str(timeline.id), "reason": "asset_added", "asset_id": str(asset.id)},
        project_id=asset.project_id,
    )


@celery_app.task(bind=True, name="cutpilot.workers.tasks.media.process_upload", max_retries=2)
@job_task
def process_upload(ctx: JobContext, session: Session, *, upload_session_id: str) -> dict[str, Any]:
    storage = get_storage()
    upload = session.get(UploadSession, uuid.UUID(upload_session_id))
    if upload is None or upload.asset_id is None:
        raise ValidationFailed("Upload session not found")
    asset = session.get(MediaAsset, upload.asset_id)
    if asset is None:
        raise ValidationFailed("Asset not found")
    asset.status = "processing"
    session.commit()
    sync_publisher.publish(
        "upload.processing", {"asset_id": str(asset.id)}, project_id=asset.project_id
    )

    ctx.progress(0.02, "Assembling upload")
    local = _assemble_upload(session, upload, ctx)
    try:
        validate_file_contents(local, asset.media_type)
        ctx.progress(0.12, "Hashing")
        content_hash = sha256_file(local)
        asset.content_hash = content_hash

        # Duplicate detection: identical bytes already in this project.
        dup = (
            session.execute(
                select(MediaAsset).where(
                    MediaAsset.project_id == asset.project_id,
                    MediaAsset.kind == "original",
                    MediaAsset.content_hash == content_hash,
                    MediaAsset.id != asset.id,
                    MediaAsset.status == "ready",
                )
            )
            .scalars()
            .first()
        )
        if dup is not None:
            asset.status = "duplicate"
            asset.error = f"Identical to {dup.filename}"
            asset.extra = {**asset.extra, "duplicate_of": str(dup.id)}
            session.commit()
            sync_publisher.publish(
                "upload.duplicate",
                {"asset_id": str(asset.id), "duplicate_of": str(dup.id)},
                project_id=asset.project_id,
            )
            return {"asset_id": str(asset.id), "duplicate_of": str(dup.id)}

        ctx.progress(0.15, "Reading metadata")
        info = ffprobe(local)
        if asset.media_type == "video" and not info.has_video and info.has_audio:
            asset.media_type = "audio"
        if asset.media_type == "image" and not info.raw.get("is_image") and info.has_video:
            asset.media_type = "video"
        _save_metadata(session, asset, info)

        # Persist the original (immutable from here on).
        ctx.progress(0.2, "Storing original")
        storage.put_file(asset.storage_key, local, content_type=asset.mime_type)
        asset.size_bytes = storage.size(asset.storage_key)
        session.commit()
        return _process_asset_derivatives(ctx, session, asset, info, work=_work_dir(ctx.id))
    finally:
        shutil.rmtree(_work_dir(ctx.id), ignore_errors=True)


def _process_asset_derivatives(
    ctx: JobContext, session: Session, asset: MediaAsset, info: MediaInfo, *, work: Path
) -> dict[str, Any]:
    storage = get_storage()
    result: dict[str, Any] = {"asset_id": str(asset.id)}
    with storage.as_local_file(asset.storage_key) as src:
        # Thumbnail
        ctx.progress(0.25, "Generating thumbnail")
        thumb = work / "thumb.jpg"
        if info.has_video:
            make_thumbnail(src, thumb, at=min(1.0, info.duration * 0.1) if info.duration else 0.0)
        elif asset.media_type == "image":
            make_image_thumbnail(src, thumb)
        if thumb.is_file():
            key = build_key(asset.project_id, "thumbnails", f"{asset.id}.jpg")
            storage.put_file(key, thumb, "image/jpeg")
            t = _add_derived(
                session,
                asset,
                kind="thumbnail",
                media_type="image",
                filename=f"{asset.id}.jpg",
                key=key,
                mime="image/jpeg",
                size=storage.size(key),
            )
            result["thumbnail_asset_id"] = str(t.id)

        if ctx.is_cancelled():
            raise JobCancelled()

        # Proxy
        if info.has_video:
            ctx.progress(0.3, "Encoding proxy")
            proxy = work / "proxy.mp4"
            cmd = make_proxy(
                src,
                proxy,
                info,
                on_progress=lambda f: ctx.progress(0.3 + 0.45 * f, "Encoding proxy"),
                check_cancel=ctx.is_cancelled,
            )
            pinfo = ffprobe(proxy)
            key = build_key(asset.project_id, "proxies", f"{asset.id}.mp4")
            storage.put_file(key, proxy, "video/mp4")
            p = _add_derived(
                session,
                asset,
                kind="proxy",
                media_type="video",
                filename=f"{asset.id}.mp4",
                key=key,
                mime="video/mp4",
                size=storage.size(key),
                extra={"ffmpeg": cmd},
            )
            _save_metadata(session, p, pinfo)
            result["proxy_asset_id"] = str(p.id)
        elif info.has_audio:
            ctx.progress(0.3, "Encoding audio proxy")
            proxy = work / "proxy.m4a"
            make_audio_proxy(
                src,
                proxy,
                info,
                on_progress=lambda f: ctx.progress(0.3 + 0.3 * f, "Encoding audio proxy"),
            )
            key = build_key(asset.project_id, "proxies", f"{asset.id}.m4a")
            storage.put_file(key, proxy, "audio/mp4")
            p = _add_derived(
                session,
                asset,
                kind="proxy",
                media_type="audio",
                filename=f"{asset.id}.m4a",
                key=key,
                mime="audio/mp4",
                size=storage.size(key),
            )
            result["proxy_asset_id"] = str(p.id)

        # Audio extraction + waveform
        if info.has_audio:
            ctx.progress(0.78, "Extracting audio")
            wav = work / "audio.wav"
            extract_audio(src, wav, info)
            ctx.progress(0.9, "Computing waveform")
            peaks = compute_waveform_peaks(wav)
            key = build_key(asset.project_id, "audio", f"{asset.id}.wav")
            storage.put_file(key, wav, "audio/wav")
            a = _add_derived(
                session,
                asset,
                kind="audio",
                media_type="audio",
                filename=f"{asset.id}.wav",
                key=key,
                mime="audio/wav",
                size=storage.size(key),
                extra={"sample_rate": 16000, "channels": 1},
            )
            result["audio_asset_id"] = str(a.id)
            wkey = build_key(asset.project_id, "analysis", f"{asset.id}.waveform.json")
            storage.put_bytes(wkey, dumps_waveform(peaks), "application/json")
            asset.extra = {**asset.extra, "waveform_key": wkey}

    asset.status = "ready"
    asset.error = None
    session.commit()
    ctx.progress(0.95, "Updating timeline")
    if asset.kind == "original" and (info.has_video or info.has_audio):
        _add_to_primary_timeline(session, asset, info)
    sync_publisher.publish(
        "upload.completed", {"asset_id": str(asset.id), **result}, project_id=asset.project_id
    )
    return result


@celery_app.task(bind=True, name="cutpilot.workers.tasks.media.reprocess_asset", max_retries=1)
@job_task
def reprocess_asset(ctx: JobContext, session: Session, *, asset_id: str) -> dict[str, Any]:
    """Regenerate derived assets for an existing original (e.g. after a proxy height change)."""
    asset = session.get(MediaAsset, uuid.UUID(asset_id))
    if asset is None:
        raise ValidationFailed("Asset not found")
    storage = get_storage()
    for d in list(asset.derived):
        storage.delete(d.storage_key)
        session.delete(d)
    session.flush()
    with storage.as_local_file(asset.storage_key) as src:
        info = ffprobe(src)
    _save_metadata(session, asset, info)
    work = _work_dir(ctx.id)
    try:
        return _process_asset_derivatives(ctx, session, asset, info, work=work)
    finally:
        shutil.rmtree(work, ignore_errors=True)

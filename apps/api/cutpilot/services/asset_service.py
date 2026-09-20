"""Chunked uploads, asset listing/serialisation, deletion."""

from __future__ import annotations

import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import aiofiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cutpilot.core.config import get_settings
from cutpilot.core.errors import ConflictError, NotFoundError, ValidationFailed
from cutpilot.db.models import Job, MediaAsset, Project, UploadSession, User
from cutpilot.media.validation import safe_filename, validate_upload_request
from cutpilot.schemas.asset import AssetOut, MediaMetadataOut
from cutpilot.services import job_service
from cutpilot.services.events import publish_async
from cutpilot.storage import build_key, get_storage

MIME_BY_EXT = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

STORAGE_DIR_BY_KIND = {
    "original": "originals",
    "broll": "originals",
    "music": "originals",
    "image": "originals",
}


def chunk_dir(upload_id: uuid.UUID) -> Path:
    return Path(get_settings().work_dir) / "uploads" / str(upload_id)


def serialize_asset(asset: MediaAsset, derived: list[MediaAsset] | None = None) -> AssetOut:
    # Built explicitly: `asset.metadata` would resolve to SQLAlchemy's MetaData, not our relation.
    out = AssetOut(
        id=asset.id,
        project_id=asset.project_id,
        parent_asset_id=asset.parent_asset_id,
        kind=asset.kind,
        media_type=asset.media_type,
        filename=asset.filename,
        mime_type=asset.mime_type,
        size_bytes=asset.size_bytes,
        content_hash=asset.content_hash,
        status=asset.status,
        error=asset.error,
        role=asset.role,
        extra=asset.extra,
        metadata=MediaMetadataOut.model_validate(asset.metadata_) if asset.metadata_ else None,
        stream_url=f"/api/assets/{asset.id}/stream",
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )
    for d in derived or []:
        if d.kind == "proxy":
            out.proxy_asset_id = d.id
        elif d.kind == "audio":
            out.audio_asset_id = d.id
        elif d.kind == "thumbnail":
            out.thumbnail_url = f"/api/assets/{asset.id}/thumbnail"
    if asset.media_type == "image" and asset.kind != "thumbnail":
        out.thumbnail_url = out.thumbnail_url or out.stream_url
    if asset.extra.get("waveform_key"):
        out.waveform_url = f"/api/assets/{asset.id}/waveform"
    return out


async def list_assets(
    db: AsyncSession,
    project: Project,
    *,
    kinds: tuple[str, ...] = ("original", "broll", "music", "image", "render", "export"),
) -> list[AssetOut]:
    rows = (
        (
            await db.execute(
                select(MediaAsset)
                .where(MediaAsset.project_id == project.id, MediaAsset.kind.in_(kinds))
                .options(selectinload(MediaAsset.metadata_), selectinload(MediaAsset.derived))
                .order_by(MediaAsset.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [serialize_asset(a, a.derived) for a in rows]


async def get_asset(db: AsyncSession, asset_id: uuid.UUID) -> MediaAsset:
    asset = (
        await db.execute(
            select(MediaAsset)
            .where(MediaAsset.id == asset_id)
            .options(selectinload(MediaAsset.metadata_), selectinload(MediaAsset.derived))
        )
    ).scalar_one_or_none()
    if asset is None:
        raise NotFoundError("Asset not found")
    return asset


async def get_asset_out(db: AsyncSession, asset_id: uuid.UUID) -> AssetOut:
    asset = await get_asset(db, asset_id)
    return serialize_asset(asset, asset.derived)


async def find_duplicate(
    db: AsyncSession, project: Project, content_hash: str
) -> MediaAsset | None:
    return (
        (
            await db.execute(
                select(MediaAsset)
                .where(
                    MediaAsset.project_id == project.id,
                    MediaAsset.content_hash == content_hash,
                    MediaAsset.kind.in_(["original", "broll", "music", "image"]),
                    MediaAsset.status == "ready",
                )
                .options(selectinload(MediaAsset.metadata_), selectinload(MediaAsset.derived))
            )
        )
        .scalars()
        .first()
    )


async def init_upload(
    db: AsyncSession,
    project: Project,
    user: User,
    *,
    filename: str,
    mime_type: str,
    size_bytes: int,
    client_hash: str | None,
    kind: str,
    role: str | None,
) -> tuple[UploadSession | None, MediaAsset | None]:
    if kind not in STORAGE_DIR_BY_KIND:
        raise ValidationFailed("Invalid asset kind")
    validate_upload_request(filename, mime_type, size_bytes)
    if client_hash:
        dup = await find_duplicate(db, project, client_hash)
        if dup is not None:
            return None, dup
    settings = get_settings()
    chunk = settings.upload_chunk_size
    total = max(1, -(-size_bytes // chunk))
    ext = Path(filename).suffix.lower()
    upload = UploadSession(
        project_id=project.id,
        user_id=user.id,
        filename=safe_filename(filename),
        mime_type=MIME_BY_EXT.get(ext, mime_type.split(";")[0] or "application/octet-stream"),
        size_bytes=size_bytes,
        chunk_size=chunk,
        total_chunks=total,
        received_chunks=[],
        client_hash=client_hash,
        kind=kind,
        role=role,
    )
    db.add(upload)
    await db.commit()
    await db.refresh(upload)
    chunk_dir(upload.id).mkdir(parents=True, exist_ok=True)
    await publish_async(
        "upload.started",
        {"upload_id": str(upload.id), "filename": upload.filename},
        project_id=project.id,
    )
    return upload, None


async def get_upload(db: AsyncSession, project: Project, upload_id: uuid.UUID) -> UploadSession:
    upload = await db.get(UploadSession, upload_id)
    if upload is None or upload.project_id != project.id:
        raise NotFoundError("Upload not found")
    return upload


async def receive_chunk(
    db: AsyncSession, upload: UploadSession, index: int, stream
) -> UploadSession:  # type: ignore[no-untyped-def]
    if upload.status != "open":
        raise ConflictError("Upload is no longer accepting chunks")
    if index < 0 or index >= upload.total_chunks:
        raise ValidationFailed("Chunk index out of range")
    directory = chunk_dir(upload.id)
    directory.mkdir(parents=True, exist_ok=True)
    part = directory / f"chunk_{index:06d}"
    tmp = part.with_suffix(".part")
    expected = (
        upload.chunk_size
        if index < upload.total_chunks - 1
        else upload.size_bytes - upload.chunk_size * (upload.total_chunks - 1)
    )
    written = 0
    async with aiofiles.open(tmp, "wb") as fh:
        async for data in stream:
            written += len(data)
            if written > upload.chunk_size:
                tmp.unlink(missing_ok=True)
                raise ValidationFailed("Chunk larger than the negotiated chunk size")
            await fh.write(data)
    if written != expected:
        tmp.unlink(missing_ok=True)
        raise ValidationFailed(f"Chunk {index} has {written} bytes, expected {expected}")
    tmp.replace(part)
    # Serialize the bookkeeping update: chunks arrive in parallel and would otherwise clobber each other.
    locked = (
        await db.execute(
            select(UploadSession).where(UploadSession.id == upload.id).with_for_update()
        )
    ).scalar_one()
    locked.received_chunks = sorted({*locked.received_chunks, index})
    await db.commit()
    await db.refresh(locked)
    return locked


def chunks_on_disk(upload: UploadSession) -> list[int]:
    """Indices whose chunk file exists with the expected size (the source of truth for completeness)."""
    directory = chunk_dir(upload.id)
    present: list[int] = []
    for index in range(upload.total_chunks):
        part = directory / f"chunk_{index:06d}"
        expected = (
            upload.chunk_size
            if index < upload.total_chunks - 1
            else upload.size_bytes - upload.chunk_size * (upload.total_chunks - 1)
        )
        try:
            if part.stat().st_size == expected:
                present.append(index)
        except OSError:
            continue
    return present


async def complete_upload(
    db: AsyncSession, project: Project, user: User, upload: UploadSession
) -> tuple[MediaAsset, Job]:
    if upload.status == "completed" and upload.asset_id:
        asset = await get_asset(db, upload.asset_id)
        job = (
            (
                await db.execute(
                    select(Job).where(Job.meta["upload_session_id"].as_string() == str(upload.id))
                )
            )
            .scalars()
            .first()
            if get_settings().database_url.startswith("postgresql")
            else None
        )
        if job is None:
            job = (
                (
                    await db.execute(
                        select(Job)
                        .where(Job.project_id == project.id, Job.type == "UPLOAD_PROCESSING")
                        .order_by(Job.created_at.desc())
                    )
                )
                .scalars()
                .first()
            )
        if job is not None:
            return asset, job
    present = set(chunks_on_disk(upload))
    if present != set(upload.received_chunks):
        upload.received_chunks = sorted(present)
        await db.commit()
    missing = [i for i in range(upload.total_chunks) if i not in present]
    if missing:
        raise ValidationFailed(
            "Upload incomplete",
            details={
                "missing_chunks": missing[:200],
                "missing_count": len(missing),
                "received": len(present),
                "total": upload.total_chunks,
            },
        )
    ext = Path(upload.filename).suffix.lower()
    media_type = (
        "image"
        if upload.kind == "image"
        else (
            "audio"
            if upload.kind == "music"
            else {"video": "video", "audio": "audio", "image": "image"}[_family(ext)]
        )
    )
    asset = MediaAsset(
        id=uuid.uuid4(),
        project_id=project.id,
        kind=upload.kind,
        media_type=media_type,
        filename=upload.filename,
        mime_type=upload.mime_type,
        size_bytes=upload.size_bytes,
        status="pending",
        role=upload.role,
        content_hash=upload.client_hash,
    )
    asset.storage_key = build_key(project.id, STORAGE_DIR_BY_KIND[upload.kind], f"{asset.id}{ext}")
    db.add(asset)
    await db.flush()
    upload.asset_id = asset.id
    upload.status = "completed"
    upload.completed_at = datetime.now(UTC)
    await db.commit()
    job = await job_service.create_job(
        db,
        user_id=user.id,
        project_id=project.id,
        job_type="UPLOAD_PROCESSING",
        meta={
            "asset_id": str(asset.id),
            "upload_session_id": str(upload.id),
            "filename": asset.filename,
        },
    )
    from cutpilot.workers.tasks.media import process_upload

    task = process_upload.apply_async(
        kwargs={"job_id": str(job.id), "upload_session_id": str(upload.id)}, queue="media"
    )
    job.celery_task_id = task.id
    await db.commit()
    await db.refresh(asset)
    return asset, job


def _family(ext: str) -> str:
    from cutpilot.media.validation import media_type_for_extension

    return media_type_for_extension(ext)


async def abort_upload(db: AsyncSession, upload: UploadSession) -> None:
    upload.status = "aborted"
    await db.commit()
    shutil.rmtree(chunk_dir(upload.id), ignore_errors=True)


async def delete_asset(db: AsyncSession, asset: MediaAsset) -> None:
    storage = get_storage()
    keys = [asset.storage_key, *[d.storage_key for d in asset.derived]]
    if asset.extra.get("waveform_key"):
        keys.append(str(asset.extra["waveform_key"]))
    await db.delete(asset)
    await db.commit()
    for key in keys:
        if "#dup:" in key:  # duplicated project: bytes belong to the source asset
            continue
        try:
            storage.delete(key)
        except Exception:  # noqa: S110 — best-effort cleanup
            pass


async def update_asset(
    db: AsyncSession, asset: MediaAsset, *, filename: str | None, role: str | None, kind: str | None
) -> MediaAsset:
    if filename is not None:
        asset.filename = safe_filename(filename)
    if role is not None:
        asset.role = role or None
    if kind is not None:
        if kind not in ("original", "broll", "music", "image"):
            raise ValidationFailed("Invalid kind")
        asset.kind = kind
    await db.commit()
    await db.refresh(asset)
    return asset


def resolve_storage_key(asset: MediaAsset) -> str:
    """Duplicated projects reference the source bytes via extra.source_storage_key."""
    if "#dup:" in asset.storage_key:
        return str(asset.extra.get("source_storage_key", asset.storage_key.split("#dup:")[0]))
    return asset.storage_key

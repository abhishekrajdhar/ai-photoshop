from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse

from cutpilot.api.deps import CurrentUser, DBSession, OwnedProject, get_owned_project, rate_limit
from cutpilot.core.errors import NotFoundError
from cutpilot.db.models import MediaAsset, Project
from cutpilot.schemas.asset import (
    AssetOut,
    AssetUpdate,
    UploadCompleteResponse,
    UploadInitRequest,
    UploadInitResponse,
    UploadStatusOut,
)
from cutpilot.schemas.common import OkResponse
from cutpilot.services import asset_service as svc
from cutpilot.storage import get_storage

router = APIRouter(tags=["assets"], dependencies=[Depends(rate_limit)])


# ── project-scoped upload + listing ─────────────────────────────────────────


@router.get("/projects/{project_id}/assets", response_model=list[AssetOut])
async def list_assets(project: OwnedProject, db: DBSession) -> list[AssetOut]:
    return await svc.list_assets(db, project)


@router.post("/projects/{project_id}/uploads", response_model=UploadInitResponse, status_code=201)
async def init_upload(
    body: UploadInitRequest, project: OwnedProject, user: CurrentUser, db: DBSession
) -> UploadInitResponse:
    upload, dup = await svc.init_upload(
        db,
        project,
        user,
        filename=body.filename,
        mime_type=body.mime_type,
        size_bytes=body.size_bytes,
        client_hash=body.client_hash,
        kind=body.kind,
        role=body.role,
    )
    if dup is not None:
        return UploadInitResponse(
            upload_id=None,
            chunk_size=0,
            total_chunks=0,
            received_chunks=[],
            duplicate_of=svc.serialize_asset(dup, dup.derived),
        )
    assert upload is not None
    return UploadInitResponse(
        upload_id=upload.id,
        chunk_size=upload.chunk_size,
        total_chunks=upload.total_chunks,
        received_chunks=list(upload.received_chunks),
    )


@router.get("/projects/{project_id}/uploads/{upload_id}", response_model=UploadStatusOut)
async def upload_status(
    upload_id: uuid.UUID, project: OwnedProject, db: DBSession
) -> UploadStatusOut:
    upload = await svc.get_upload(db, project, upload_id)
    return UploadStatusOut(
        upload_id=upload.id,
        status=upload.status,
        received_chunks=svc.chunks_on_disk(upload)
        if upload.status == "open"
        else list(upload.received_chunks),
        total_chunks=upload.total_chunks,
        asset_id=upload.asset_id,
    )


@router.put(
    "/projects/{project_id}/uploads/{upload_id}/chunks/{index}", response_model=UploadStatusOut
)
async def upload_chunk(
    upload_id: uuid.UUID, index: int, request: Request, project: OwnedProject, db: DBSession
) -> UploadStatusOut:
    upload = await svc.get_upload(db, project, upload_id)
    upload = await svc.receive_chunk(db, upload, index, request.stream())
    return UploadStatusOut(
        upload_id=upload.id,
        status=upload.status,
        received_chunks=list(upload.received_chunks),
        total_chunks=upload.total_chunks,
        asset_id=upload.asset_id,
    )


@router.post(
    "/projects/{project_id}/uploads/{upload_id}/complete", response_model=UploadCompleteResponse
)
async def complete_upload(
    upload_id: uuid.UUID, project: OwnedProject, user: CurrentUser, db: DBSession
) -> UploadCompleteResponse:
    upload = await svc.get_upload(db, project, upload_id)
    asset, job = await svc.complete_upload(db, project, user, upload)
    return UploadCompleteResponse(asset=await svc.get_asset_out(db, asset.id), job_id=job.id)


@router.delete("/projects/{project_id}/uploads/{upload_id}", response_model=OkResponse)
async def abort_upload(upload_id: uuid.UUID, project: OwnedProject, db: DBSession) -> OkResponse:
    upload = await svc.get_upload(db, project, upload_id)
    await svc.abort_upload(db, upload)
    return OkResponse()


@router.post(
    "/projects/{project_id}/assets", response_model=UploadCompleteResponse, status_code=201
)
async def upload_small_file(
    file: UploadFile,
    project: OwnedProject,
    user: CurrentUser,
    db: DBSession,
    kind: str = "original",
    role: str | None = None,
) -> UploadCompleteResponse:
    """Convenience single-request upload (bounded by the request size limit). Uses the chunked pipeline internally."""
    data = await file.read()
    upload, dup = await svc.init_upload(
        db,
        project,
        user,
        filename=file.filename or "upload",
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=len(data),
        client_hash=None,
        kind=kind,
        role=role,
    )
    assert upload is not None and dup is None

    # Split into chunk-size pieces so the session bookkeeping stays exact.
    for idx in range(upload.total_chunks):
        piece = data[idx * upload.chunk_size : (idx + 1) * upload.chunk_size]

        async def _gen(p: bytes = piece):  # type: ignore[no-untyped-def]
            yield p

        upload = await svc.receive_chunk(db, upload, idx, _gen())
    asset, job = await svc.complete_upload(db, project, user, upload)
    return UploadCompleteResponse(asset=await svc.get_asset_out(db, asset.id), job_id=job.id)


# ── asset-scoped routes ──────────────────────────────────────────────────────


async def _owned_asset(
    asset_id: uuid.UUID, user: CurrentUser, db: DBSession
) -> tuple[MediaAsset, Project]:
    asset = await svc.get_asset(db, asset_id)
    project = await get_owned_project(asset.project_id, user, db)
    return asset, project


@router.get("/assets/{asset_id}", response_model=AssetOut)
async def get_asset(owned: tuple[MediaAsset, Project] = Depends(_owned_asset)) -> AssetOut:
    asset, _ = owned
    return svc.serialize_asset(asset, asset.derived)


@router.patch("/assets/{asset_id}", response_model=AssetOut)
async def update_asset(
    body: AssetUpdate, db: DBSession, owned: tuple[MediaAsset, Project] = Depends(_owned_asset)
) -> AssetOut:
    asset, _ = owned
    asset = await svc.update_asset(
        db, asset, filename=body.filename, role=body.role, kind=body.kind
    )
    return await svc.get_asset_out(db, asset.id)


@router.delete("/assets/{asset_id}", response_model=OkResponse)
async def delete_asset(
    db: DBSession, owned: tuple[MediaAsset, Project] = Depends(_owned_asset)
) -> OkResponse:
    asset, _ = owned
    await svc.delete_asset(db, asset)
    return OkResponse()


def _serve(
    request: Request, asset: MediaAsset, *, download: bool = False, mime: str | None = None
) -> Response:
    storage = get_storage()
    key = svc.resolve_storage_key(asset)
    signed = storage.signed_url(key, filename=asset.filename if download else None)
    if signed:
        return RedirectResponse(signed, status_code=307)
    path = storage.local_path(key)
    if path is None:
        raise NotFoundError("File not available")
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{asset.filename}"'
    return FileResponse(path, media_type=mime or asset.mime_type, headers=headers)


@router.get("/assets/{asset_id}/stream")
async def stream_asset(
    request: Request, owned: tuple[MediaAsset, Project] = Depends(_owned_asset)
) -> Response:
    """Serve the best browser-playable representation: proxy when available, else the file itself."""
    asset, _ = owned
    proxy = next((d for d in asset.derived if d.kind == "proxy"), None)
    return _serve(request, proxy or asset)


@router.get("/assets/{asset_id}/original")
async def stream_original(
    request: Request, owned: tuple[MediaAsset, Project] = Depends(_owned_asset)
) -> Response:
    asset, _ = owned
    return _serve(request, asset)


@router.get("/assets/{asset_id}/download")
async def download_asset(
    request: Request, owned: tuple[MediaAsset, Project] = Depends(_owned_asset)
) -> Response:
    asset, _ = owned
    return _serve(request, asset, download=True)


@router.get("/assets/{asset_id}/thumbnail")
async def asset_thumbnail(
    request: Request, owned: tuple[MediaAsset, Project] = Depends(_owned_asset)
) -> Response:
    asset, _ = owned
    thumb = next((d for d in asset.derived if d.kind == "thumbnail"), None)
    if thumb is None:
        if asset.media_type == "image":
            return _serve(request, asset)
        raise NotFoundError("No thumbnail")
    return _serve(request, thumb, mime="image/jpeg")


@router.get("/assets/{asset_id}/waveform")
async def asset_waveform(owned: tuple[MediaAsset, Project] = Depends(_owned_asset)) -> Response:
    asset, _ = owned
    key = asset.extra.get("waveform_key")
    if not key:
        raise NotFoundError("No waveform")
    storage = get_storage()
    return StreamingResponse(
        storage.open_stream(str(key)),
        media_type="application/json",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/assets/{asset_id}/derived", response_model=list[AssetOut])
async def derived_assets(
    owned: tuple[MediaAsset, Project] = Depends(_owned_asset),
) -> list[AssetOut]:
    asset, _ = owned
    return [svc.serialize_asset(d) for d in asset.derived]

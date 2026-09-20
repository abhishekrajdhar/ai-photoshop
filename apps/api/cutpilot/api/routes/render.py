from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from cutpilot.api.deps import CurrentUser, DBSession, OwnedProject, get_owned_project, rate_limit
from cutpilot.schemas.render import ExportOut, ExportRequest, PresetOut, RenderOut, RenderRequest
from cutpilot.services import render_service as svc

router = APIRouter(tags=["render"], dependencies=[Depends(rate_limit)])


@router.get("/render/presets", response_model=list[PresetOut])
async def presets() -> list[PresetOut]:
    return svc.list_presets()


@router.post("/projects/{project_id}/render", response_model=RenderOut, status_code=202)
async def start_render(
    body: RenderRequest, project: OwnedProject, user: CurrentUser, db: DBSession
) -> RenderOut:
    render, _job = await svc.start_render(
        db,
        project=project,
        user=user,
        timeline_id=body.timeline_id,
        preset=body.preset,
        settings=body.settings,
        kind=body.kind,
    )
    return svc.serialize_render(render)


@router.get("/projects/{project_id}/renders", response_model=list[RenderOut])
async def list_renders(project: OwnedProject, db: DBSession) -> list[RenderOut]:
    return [svc.serialize_render(r) for r in await svc.list_renders(db, project)]


@router.get("/projects/{project_id}/renders/{render_id}", response_model=RenderOut)
async def get_render(render_id: uuid.UUID, project: OwnedProject, db: DBSession) -> RenderOut:
    return svc.serialize_render(await svc.get_render(db, project, render_id))


@router.post("/projects/{project_id}/exports", response_model=ExportOut, status_code=202)
async def start_export(
    body: ExportRequest, project: OwnedProject, user: CurrentUser, db: DBSession
) -> ExportOut:
    export, _job = await svc.start_export(
        db,
        project=project,
        user=user,
        timeline_id=body.timeline_id,
        fmt=body.format,
        preset=body.preset,
        filename=body.filename,
        settings=body.settings,
    )
    return svc.serialize_export(export)


@router.get("/projects/{project_id}/exports", response_model=list[ExportOut])
async def list_exports(project: OwnedProject, db: DBSession) -> list[ExportOut]:
    return [svc.serialize_export(e) for e in await svc.list_exports(db, project)]


@router.get("/exports/{export_id}", response_model=ExportOut)
async def get_export(export_id: uuid.UUID, user: CurrentUser, db: DBSession) -> ExportOut:
    export = await svc.get_export(db, export_id)
    await get_owned_project(export.project_id, user, db)
    return svc.serialize_export(export)

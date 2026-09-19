from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from cutpilot.api.deps import CurrentUser, DBSession, OwnedProject, rate_limit
from cutpilot.schemas.common import OkResponse, Page
from cutpilot.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from cutpilot.services import project_service

router = APIRouter(prefix="/projects", tags=["projects"], dependencies=[Depends(rate_limit)])


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(body: ProjectCreate, user: CurrentUser, db: DBSession) -> ProjectOut:
    project = await project_service.create_project(db, user, body)
    return ProjectOut.model_validate(project)


@router.get("", response_model=Page[ProjectOut])
async def list_projects(
    user: CurrentUser,
    db: DBSession,
    include_archived: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[ProjectOut]:
    rows, total, counts = await project_service.list_projects(
        db, user, include_archived=include_archived, limit=limit, offset=offset
    )
    items = []
    for p in rows:
        out = ProjectOut.model_validate(p)
        out.asset_count = counts.get(p.id, 0)
        items.append(out)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project: OwnedProject) -> ProjectOut:
    return ProjectOut.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(body: ProjectUpdate, project: OwnedProject, db: DBSession) -> ProjectOut:
    return ProjectOut.model_validate(await project_service.update_project(db, project, body))


@router.post("/{project_id}/archive", response_model=ProjectOut)
async def archive_project(project: OwnedProject, db: DBSession) -> ProjectOut:
    return ProjectOut.model_validate(await project_service.archive_project(db, project))


@router.post("/{project_id}/duplicate", response_model=ProjectOut, status_code=201)
async def duplicate_project(project: OwnedProject, user: CurrentUser, db: DBSession) -> ProjectOut:
    return ProjectOut.model_validate(await project_service.duplicate_project(db, user, project))


@router.delete("/{project_id}", response_model=OkResponse)
async def delete_project(project: OwnedProject, db: DBSession) -> OkResponse:
    await project_service.delete_project(db, project)
    return OkResponse()

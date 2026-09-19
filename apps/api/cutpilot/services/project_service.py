"""Project CRUD, duplication and archival."""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cutpilot.db.models import MediaAsset, Project, Timeline, TimelineVersion, User
from cutpilot.schemas.project import ProjectCreate, ProjectSettings, ProjectUpdate
from cutpilot.timeline.model import TimelineDocument


async def create_project(db: AsyncSession, owner: User, data: ProjectCreate) -> Project:
    project = Project(
        owner_id=owner.id,
        name=data.name.strip(),
        description=data.description,
        settings=data.settings.model_dump(),
    )
    db.add(project)
    await db.flush()
    # Every project starts with an empty primary timeline (version 1 = raw footage as uploaded).
    timeline = Timeline(project_id=project.id, name="Main", kind="main", is_primary=True)
    db.add(timeline)
    await db.flush()
    doc = TimelineDocument.empty(timeline_id=str(timeline.id), name="Main")
    version = TimelineVersion(
        timeline_id=timeline.id,
        version=1,
        label="Empty timeline",
        source="system",
        document=doc.model_dump(mode="json"),
        duration=0.0,
    )
    db.add(version)
    await db.flush()
    timeline.current_version_id = version.id
    await db.commit()
    await db.refresh(project)
    return project


async def list_projects(
    db: AsyncSession, owner: User, *, include_archived: bool, limit: int, offset: int
) -> tuple[list[Project], int, dict[uuid.UUID, int]]:
    query = select(Project).where(Project.owner_id == owner.id)
    if not include_archived:
        query = query.where(Project.status == "active")
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (
        (await db.execute(query.order_by(Project.updated_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    ids = [p.id for p in rows]
    counts: dict[uuid.UUID, int] = {}
    if ids:
        count_rows = await db.execute(
            select(MediaAsset.project_id, func.count())
            .where(MediaAsset.project_id.in_(ids), MediaAsset.kind == "original")
            .group_by(MediaAsset.project_id)
        )
        counts = {pid: int(c) for pid, c in count_rows.all()}
    return list(rows), int(total), counts


async def update_project(db: AsyncSession, project: Project, data: ProjectUpdate) -> Project:
    if data.name is not None:
        project.name = data.name.strip()
    if data.description is not None:
        project.description = data.description
    if data.settings is not None:
        project.settings = data.settings.model_dump()
    if data.status is not None:
        project.status = data.status
        project.archived_at = datetime.now(UTC) if data.status == "archived" else None
    await db.commit()
    await db.refresh(project)
    return project


async def archive_project(db: AsyncSession, project: Project) -> Project:
    project.status = "archived"
    project.archived_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(project)
    return project


async def delete_project(db: AsyncSession, project: Project) -> None:
    await db.delete(project)
    await db.commit()


async def duplicate_project(db: AsyncSession, owner: User, project: Project) -> Project:
    """Copy a project's assets (by reference to the same immutable storage keys) and timelines."""
    clone = Project(
        owner_id=owner.id,
        name=f"{project.name} (copy)",
        description=project.description,
        settings=copy.deepcopy(project.settings),
    )
    db.add(clone)
    await db.flush()

    assets = (
        (await db.execute(select(MediaAsset).where(MediaAsset.project_id == project.id)))
        .scalars()
        .all()
    )
    id_map: dict[uuid.UUID, uuid.UUID] = {}
    # Originals first so parent links resolve.
    for asset in sorted(assets, key=lambda a: 0 if a.parent_asset_id is None else 1):
        new_id = uuid.uuid4()
        id_map[asset.id] = new_id
        db.add(
            MediaAsset(
                id=new_id,
                project_id=clone.id,
                parent_asset_id=id_map.get(asset.parent_asset_id)
                if asset.parent_asset_id
                else None,
                kind=asset.kind,
                media_type=asset.media_type,
                filename=asset.filename,
                # Storage keys are unique per asset; duplicates reference the source key via `extra`
                # so no bytes are copied (originals are immutable).
                storage_key=f"{asset.storage_key}#dup:{new_id}",
                mime_type=asset.mime_type,
                size_bytes=asset.size_bytes,
                content_hash=asset.content_hash,
                status=asset.status,
                role=asset.role,
                extra={
                    **asset.extra,
                    "source_storage_key": asset.storage_key,
                    "duplicated_from": str(asset.id),
                },
            )
        )

    timelines = (
        (await db.execute(select(Timeline).where(Timeline.project_id == project.id)))
        .scalars()
        .all()
    )
    for tl in timelines:
        new_tl = Timeline(
            project_id=clone.id,
            name=tl.name,
            kind=tl.kind,
            is_primary=tl.is_primary,
            settings=tl.settings,
        )
        db.add(new_tl)
        await db.flush()
        versions = (
            (
                await db.execute(
                    select(TimelineVersion)
                    .where(TimelineVersion.timeline_id == tl.id)
                    .order_by(TimelineVersion.version)
                )
            )
            .scalars()
            .all()
        )
        current_new: uuid.UUID | None = None
        for v in versions:
            doc = copy.deepcopy(v.document)
            for track in doc.get("tracks", []):
                for clip in track.get("clips", []):
                    src = clip.get("asset_id")
                    if src and uuid.UUID(src) in id_map:
                        clip["asset_id"] = str(id_map[uuid.UUID(src)])
            doc["timeline_id"] = str(new_tl.id)
            nv = TimelineVersion(
                timeline_id=new_tl.id,
                version=v.version,
                label=v.label,
                source=v.source,
                document=doc,
                duration=v.duration,
            )
            db.add(nv)
            await db.flush()
            if v.id == tl.current_version_id:
                current_new = nv.id
        new_tl.current_version_id = current_new
    await db.commit()
    await db.refresh(clone)
    return clone


def default_settings() -> dict[str, object]:
    return ProjectSettings().model_dump()

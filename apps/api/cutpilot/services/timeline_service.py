"""Timeline versioning: every edit creates an immutable new version."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cutpilot.core.errors import NotFoundError, ValidationFailed
from cutpilot.db.models import EditOperation as EditOperationRow
from cutpilot.db.models import Project, Timeline, TimelineVersion
from cutpilot.timeline.engine import ApplyResult, apply_operations
from cutpilot.timeline.model import TimelineDocument
from cutpilot.timeline.operations import EditOperation


async def get_primary_timeline(db: AsyncSession, project: Project) -> Timeline:
    tl = (
        await db.execute(
            select(Timeline).where(Timeline.project_id == project.id, Timeline.is_primary.is_(True))
        )
    ).scalar_one_or_none()
    if tl is None:
        tl = (
            (
                await db.execute(
                    select(Timeline)
                    .where(Timeline.project_id == project.id)
                    .order_by(Timeline.created_at)
                )
            )
            .scalars()
            .first()
        )
    if tl is None:
        raise NotFoundError("Project has no timeline")
    return tl


async def get_timeline(
    db: AsyncSession, project: Project, timeline_id: uuid.UUID | None
) -> Timeline:
    if timeline_id is None:
        return await get_primary_timeline(db, project)
    tl = await db.get(Timeline, timeline_id)
    if tl is None or tl.project_id != project.id:
        raise NotFoundError("Timeline not found")
    return tl


async def list_timelines(db: AsyncSession, project: Project) -> list[Timeline]:
    rows = (
        (
            await db.execute(
                select(Timeline)
                .where(Timeline.project_id == project.id)
                .order_by(Timeline.created_at)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def current_version(db: AsyncSession, timeline: Timeline) -> TimelineVersion:
    if timeline.current_version_id is not None:
        v = await db.get(TimelineVersion, timeline.current_version_id)
        if v is not None:
            return v
    v = (
        (
            await db.execute(
                select(TimelineVersion)
                .where(TimelineVersion.timeline_id == timeline.id)
                .order_by(TimelineVersion.version.desc())
            )
        )
        .scalars()
        .first()
    )
    if v is None:
        raise NotFoundError("Timeline has no versions")
    return v


async def list_versions(db: AsyncSession, timeline: Timeline) -> list[TimelineVersion]:
    rows = (
        (
            await db.execute(
                select(TimelineVersion)
                .where(TimelineVersion.timeline_id == timeline.id)
                .order_by(TimelineVersion.version)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def operation_counts(db: AsyncSession, version_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not version_ids:
        return {}
    rows = await db.execute(
        select(EditOperationRow.timeline_version_id, func.count())
        .where(EditOperationRow.timeline_version_id.in_(version_ids))
        .group_by(EditOperationRow.timeline_version_id)
    )
    return {vid: int(c) for vid, c in rows.all() if vid is not None}


def load_document(version: TimelineVersion) -> TimelineDocument:
    try:
        return TimelineDocument.model_validate(version.document)
    except Exception as exc:  # corrupt document should never happen; surface clearly
        raise ValidationFailed(f"Timeline document is invalid: {exc}") from exc


async def _next_version_number(db: AsyncSession, timeline: Timeline) -> int:
    n = (
        await db.execute(
            select(func.max(TimelineVersion.version)).where(
                TimelineVersion.timeline_id == timeline.id
            )
        )
    ).scalar_one()
    return int(n or 0) + 1


async def commit_version(
    db: AsyncSession,
    *,
    project: Project,
    timeline: Timeline,
    document: TimelineDocument,
    label: str,
    source: str,
    parent: TimelineVersion | None,
    operations: list[EditOperation] | None = None,
    chat_message_id: uuid.UUID | None = None,
) -> TimelineVersion:
    document.timeline_id = str(timeline.id)
    document.sort()
    version = TimelineVersion(
        timeline_id=timeline.id,
        version=await _next_version_number(db, timeline),
        parent_version_id=parent.id if parent else None,
        label=label[:200],
        source=source,
        document=document.model_dump(mode="json"),
        duration=document.duration(),
    )
    db.add(version)
    await db.flush()
    for op in operations or []:
        db.add(
            EditOperationRow(
                project_id=project.id,
                timeline_version_id=version.id,
                chat_message_id=chat_message_id,
                type=op.type,
                source_clip_id=op.source_clip_id or op.asset_id,
                start=op.start if op.start is not None else op.timestamp,
                end=op.end,
                params={**op.params, "op": op.model_dump(mode="json")},
                confidence=op.confidence,
                reason=op.reason,
                source=op.source,
                reversible=op.reversible,
                status="applied",
            )
        )
    timeline.current_version_id = version.id
    await db.commit()
    await db.refresh(version)
    await db.refresh(timeline)
    return version


async def apply_ops_to_timeline(
    db: AsyncSession,
    *,
    project: Project,
    timeline: Timeline,
    operations: list[EditOperation],
    label: str,
    source: str,
    chat_message_id: uuid.UUID | None = None,
) -> tuple[TimelineVersion, TimelineVersion, ApplyResult]:
    """Apply operations to the current version, producing a new version. Returns (old, new, result)."""
    base = await current_version(db, timeline)
    doc = load_document(base)
    result = apply_operations(doc, operations)
    if not result.applied:
        reasons = "; ".join(f"{op.type}: {why}" for op, why in result.rejected[:5])
        raise ValidationFailed("No operations could be applied", details={"rejected": reasons})
    new_version = await commit_version(
        db,
        project=project,
        timeline=timeline,
        document=result.document,
        label=label,
        source=source,
        parent=base,
        operations=result.applied,
        chat_message_id=chat_message_id,
    )
    return base, new_version, result


async def save_document(
    db: AsyncSession, *, project: Project, timeline: Timeline, document: dict[str, Any], label: str
) -> TimelineVersion:
    base = await current_version(db, timeline)
    doc = TimelineDocument.model_validate(document)
    return await commit_version(
        db,
        project=project,
        timeline=timeline,
        document=doc,
        label=label,
        source="user",
        parent=base,
    )


async def restore_version(
    db: AsyncSession, *, project: Project, timeline: Timeline, version: TimelineVersion
) -> TimelineVersion:
    """Restoring creates a new version whose document equals the restored one (history is preserved)."""
    base = await current_version(db, timeline)
    if version.id == base.id:
        return base
    doc = load_document(version)
    return await commit_version(
        db,
        project=project,
        timeline=timeline,
        document=doc,
        label=f"Restored v{version.version}",
        source="user",
        parent=base,
    )


async def undo(db: AsyncSession, timeline: Timeline) -> TimelineVersion:
    """Undo moves the current pointer to the parent version (redo moves forward again)."""
    cur = await current_version(db, timeline)
    if cur.parent_version_id is None:
        raise ValidationFailed("Nothing to undo")
    parent = await db.get(TimelineVersion, cur.parent_version_id)
    if parent is None:
        raise ValidationFailed("Nothing to undo")
    timeline.current_version_id = parent.id
    await db.commit()
    await db.refresh(timeline)
    return parent


async def redo(db: AsyncSession, timeline: Timeline) -> TimelineVersion:
    cur = await current_version(db, timeline)
    child = (
        (
            await db.execute(
                select(TimelineVersion)
                .where(
                    TimelineVersion.timeline_id == timeline.id,
                    TimelineVersion.parent_version_id == cur.id,
                )
                .order_by(TimelineVersion.version.desc())
            )
        )
        .scalars()
        .first()
    )
    if child is None:
        raise ValidationFailed("Nothing to redo")
    timeline.current_version_id = child.id
    await db.commit()
    await db.refresh(timeline)
    return child


async def has_redo(db: AsyncSession, timeline: Timeline, cur: TimelineVersion) -> bool:
    child = (
        await db.execute(
            select(TimelineVersion.id).where(
                TimelineVersion.timeline_id == timeline.id,
                TimelineVersion.parent_version_id == cur.id,
            )
        )
    ).first()
    return child is not None


async def create_timeline(
    db: AsyncSession,
    *,
    project: Project,
    name: str,
    kind: str,
    document: TimelineDocument,
    label: str = "Created",
    source: str = "user",
) -> Timeline:
    timeline = Timeline(project_id=project.id, name=name, kind=kind, is_primary=False)
    db.add(timeline)
    await db.flush()
    document.timeline_id = str(timeline.id)
    document.name = name
    version = TimelineVersion(
        timeline_id=timeline.id,
        version=1,
        label=label,
        source=source,
        document=document.model_dump(mode="json"),
        duration=document.duration(),
    )
    db.add(version)
    await db.flush()
    timeline.current_version_id = version.id
    await db.commit()
    await db.refresh(timeline)
    return timeline


def compare_documents(a: TimelineDocument, b: TimelineDocument) -> dict[str, Any]:
    def index(doc: TimelineDocument) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for track, clip in doc.all_clips():
            out[clip.id] = {
                "id": clip.id,
                "track_id": track.id,
                "kind": clip.kind,
                "name": clip.name,
                "timeline_start": clip.timeline_start,
                "duration": clip.duration,
                "source_in": clip.source_in,
                "source_out": clip.source_out,
                "effects": len(clip.effects),
            }
        return out

    ia, ib = index(a), index(b)
    added = [ib[k] for k in ib if k not in ia]
    removed = [ia[k] for k in ia if k not in ib]
    changed = [{"before": ia[k], "after": ib[k]} for k in ia if k in ib and ia[k] != ib[k]]
    return {
        "duration_delta": round(b.duration() - a.duration(), 3),
        "added_clips": added,
        "removed_clips": removed,
        "changed_clips": changed,
    }

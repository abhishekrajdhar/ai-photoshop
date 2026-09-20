"""Synchronous timeline helpers for workers (mirror of timeline_service for sync sessions)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cutpilot.db.models import Timeline, TimelineVersion
from cutpilot.timeline.model import TimelineDocument


def primary_timeline(session: Session, project_id: uuid.UUID) -> Timeline | None:
    tl = session.execute(
        select(Timeline).where(Timeline.project_id == project_id, Timeline.is_primary.is_(True))
    ).scalar_one_or_none()
    if tl is None:
        tl = (
            session.execute(
                select(Timeline)
                .where(Timeline.project_id == project_id)
                .order_by(Timeline.created_at)
            )
            .scalars()
            .first()
        )
    return tl


def current_version(session: Session, timeline: Timeline) -> TimelineVersion | None:
    if timeline.current_version_id:
        v = session.get(TimelineVersion, timeline.current_version_id)
        if v:
            return v
    return (
        session.execute(
            select(TimelineVersion)
            .where(TimelineVersion.timeline_id == timeline.id)
            .order_by(TimelineVersion.version.desc())
        )
        .scalars()
        .first()
    )


def commit_version(
    session: Session,
    timeline: Timeline,
    document: TimelineDocument,
    *,
    label: str,
    source: str,
    parent: TimelineVersion | None,
) -> TimelineVersion:
    document.timeline_id = str(timeline.id)
    document.sort()
    n = (
        session.execute(
            select(func.max(TimelineVersion.version)).where(
                TimelineVersion.timeline_id == timeline.id
            )
        ).scalar_one()
        or 0
    )
    version = TimelineVersion(
        timeline_id=timeline.id,
        version=int(n) + 1,
        parent_version_id=parent.id if parent else None,
        label=label[:200],
        source=source,
        document=document.model_dump(mode="json"),
        duration=document.duration(),
    )
    session.add(version)
    session.flush()
    timeline.current_version_id = version.id
    session.commit()
    return version


def create_timeline(
    session: Session,
    project_id: uuid.UUID,
    *,
    name: str,
    kind: str,
    document: TimelineDocument,
    label: str,
    source: str,
) -> Timeline:
    timeline = Timeline(project_id=project_id, name=name, kind=kind, is_primary=False)
    session.add(timeline)
    session.flush()
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
    session.add(version)
    session.flush()
    timeline.current_version_id = version.id
    session.commit()
    return timeline

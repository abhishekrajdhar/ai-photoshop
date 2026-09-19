from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cutpilot.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from cutpilot.db.models.project import Project


class Timeline(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named sequence in a project (main edit, a Short, an alternate cut…)."""

    __tablename__ = "timelines"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # main | short | alternate
    kind: Mapped[str] = mapped_column(String(32), default="main", nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("timeline_versions.id", ondelete="SET NULL", use_alter=True)
    )
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)

    project: Mapped[Project] = relationship(back_populates="timelines")
    versions: Mapped[list[TimelineVersion]] = relationship(
        back_populates="timeline",
        cascade="all, delete-orphan",
        foreign_keys="TimelineVersion.timeline_id",
        order_by="TimelineVersion.version",
    )


class TimelineVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable snapshot of a timeline document. The `document` JSON is the source of truth."""

    __tablename__ = "timeline_versions"

    timeline_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("timelines.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("timeline_versions.id", ondelete="SET NULL")
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # user | ai | system
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    document: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    duration: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    timeline: Mapped[Timeline] = relationship(back_populates="versions", foreign_keys=[timeline_id])
    operations: Mapped[list[EditOperation]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


class EditOperation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A structured edit decision (from AI or user) applied to produce a timeline version."""

    __tablename__ = "edit_operations"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    timeline_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("timeline_versions.id", ondelete="CASCADE"), index=True
    )
    chat_message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chat_messages.id", ondelete="SET NULL")
    )
    type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    source_clip_id: Mapped[str | None] = mapped_column(String(64))
    start: Mapped[float | None] = mapped_column(Float)
    end: Mapped[float | None] = mapped_column(Float)
    params: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # ai | user | system
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    reversible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # proposed | applied | rejected
    status: Mapped[str] = mapped_column(String(16), default="proposed", nullable=False, index=True)

    version: Mapped[TimelineVersion | None] = relationship(back_populates="operations")

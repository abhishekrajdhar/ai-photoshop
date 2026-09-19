from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cutpilot.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from cutpilot.db.models.media import MediaAsset
    from cutpilot.db.models.timeline import Timeline
    from cutpilot.db.models.user import User


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    # Project-level editing settings (target platform, aspect, fps, filler words, caption style…)
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owner: Mapped[User] = relationship(back_populates="projects")
    assets: Mapped[list[MediaAsset]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    timelines: Mapped[list[Timeline]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

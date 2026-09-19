from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cutpilot.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from cutpilot.db.models.project import Project


class MediaAsset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A file stored for a project. Originals are immutable; derived assets link to a parent."""

    __tablename__ = "media_assets"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    parent_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="CASCADE"), index=True
    )
    # original | proxy | audio | thumbnail | frame | render | export | caption | broll | music | image
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # video | audio | image | text
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    # pending | processing | ready | failed
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    error: Mapped[str | None] = mapped_column(String(2000))
    # multicam camera label / role (e.g. "cam_a")
    role: Mapped[str | None] = mapped_column(String(64))
    extra: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)

    project: Mapped[Project] = relationship(back_populates="assets")
    metadata_: Mapped[MediaMetadata | None] = relationship(
        back_populates="asset", uselist=False, cascade="all, delete-orphan"
    )
    derived: Mapped[list[MediaAsset]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    parent: Mapped[MediaAsset | None] = relationship(
        back_populates="derived", remote_side="MediaAsset.id"
    )


class MediaMetadata(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FFprobe-derived technical metadata for a media asset."""

    __tablename__ = "media_metadata"

    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    container: Mapped[str | None] = mapped_column(String(64))
    video_codec: Mapped[str | None] = mapped_column(String(64))
    audio_codec: Mapped[str | None] = mapped_column(String(64))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    duration: Mapped[float | None] = mapped_column(Float)
    bitrate: Mapped[int | None] = mapped_column(BigInteger)
    audio_channels: Mapped[int | None] = mapped_column(Integer)
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    rotation: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)

    asset: Mapped[MediaAsset] = relationship(back_populates="metadata_")


class UploadSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tracks a chunked / resumable upload before it becomes a MediaAsset."""

    __tablename__ = "upload_sessions"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False)
    received_chunks: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    client_hash: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32), default="original", nullable=False)
    # open | assembling | completed | aborted
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

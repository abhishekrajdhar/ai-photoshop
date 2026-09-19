from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from cutpilot.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # UPLOAD_PROCESSING | PROXY_GENERATION | TRANSCRIPTION | SCENE_DETECTION | AUDIO_ANALYSIS |
    # VISION_ANALYSIS | EDIT_PLANNING | SHORT_GENERATION | RENDERING | EXPORT | ...
    type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    # QUEUED | RUNNING | COMPLETED | FAILED | CANCELLED
    status: Mapped[str] = mapped_column(String(16), default="QUEUED", nullable=False, index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    message: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(64), index=True)
    # arbitrary input/output details: asset_id, timeline_version_id, result keys…
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Render(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "renders"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    timeline_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("timeline_versions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("jobs.id", ondelete="SET NULL")
    )
    # preview | final
    kind: Mapped[str] = mapped_column(String(16), default="final", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="QUEUED", nullable=False)
    preset: Mapped[str] = mapped_column(String(64), nullable=False, default="custom")
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    output_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    ffmpeg_command: Mapped[str | None] = mapped_column(Text)
    duration: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)


class Export(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "exports"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    render_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("renders.id", ondelete="SET NULL")
    )
    timeline_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("timeline_versions.id", ondelete="SET NULL")
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("jobs.id", ondelete="SET NULL")
    )
    # mp4 | srt | vtt | otio | edl | fcpxml
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    preset: Mapped[str] = mapped_column(String(64), nullable=False, default="custom")
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="QUEUED", nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    output_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)

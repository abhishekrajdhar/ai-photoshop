from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cutpilot.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Transcript(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "transcripts"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    language: Mapped[str | None] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    segments: Mapped[list[TranscriptSegment]] = relationship(
        back_populates="transcript",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.start",
    )
    speakers: Mapped[list[Speaker]] = relationship(
        back_populates="transcript", cascade="all, delete-orphan"
    )


class Speaker(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "speakers"

    transcript_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("transcripts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    label: Mapped[str] = mapped_column(String(64), nullable=False)  # SPEAKER_00
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    color: Mapped[str | None] = mapped_column(String(16))

    transcript: Mapped[Transcript] = relationship(back_populates="speakers")


class TranscriptSegment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "transcript_segments"

    transcript_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("transcripts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    start: Mapped[float] = mapped_column(Float, nullable=False)
    end: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    speaker_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("speakers.id", ondelete="SET NULL")
    )
    confidence: Mapped[float | None] = mapped_column(Float)

    transcript: Mapped[Transcript] = relationship(back_populates="segments")
    words: Mapped[list[TranscriptWord]] = relationship(
        back_populates="segment", cascade="all, delete-orphan", order_by="TranscriptWord.start"
    )


class TranscriptWord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "transcript_words"

    segment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("transcript_segments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    start: Mapped[float] = mapped_column(Float, nullable=False)
    end: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(String(128), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    speaker_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("speakers.id", ondelete="SET NULL")
    )
    is_filler: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    segment: Mapped[TranscriptSegment] = relationship(back_populates="words")


class Scene(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "scenes"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    start: Mapped[float] = mapped_column(Float, nullable=False)
    end: Mapped[float] = mapped_column(Float, nullable=False)
    thumbnail_key: Mapped[str | None] = mapped_column(String(1024))
    description: Mapped[str | None] = mapped_column(Text)
    labels: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)


class AnalysisResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Cached analysis output keyed by (asset, kind, content hash, params hash)."""

    __tablename__ = "analysis_results"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="CASCADE"), index=True
    )
    # silence | filler | scenes | vision | content | highlights | audio_stats | waveform | thumbnails
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    params_hash: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    data: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)


class Caption(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A generated caption set (SRT/VTT/ASS) for a timeline version."""

    __tablename__ = "captions"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    timeline_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("timeline_versions.id", ondelete="CASCADE"), index=True
    )
    format: Mapped[str] = mapped_column(String(8), nullable=False)  # srt | vtt | ass
    style: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    cue_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Highlight(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "highlights"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="CASCADE")
    )
    start: Mapped[float] = mapped_column(Float, nullable=False)
    end: Mapped[float] = mapped_column(Float, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    caption_suggestion: Mapped[str] = mapped_column(Text, default="", nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Individual factor scores (informative, surprising, funny, emotional, hook, argument…)
    factors: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    category: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))

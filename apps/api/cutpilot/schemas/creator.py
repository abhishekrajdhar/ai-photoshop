from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from cutpilot.schemas.common import APIModel


class HighlightOut(APIModel):
    id: uuid.UUID
    asset_id: uuid.UUID | None
    start: float
    end: float
    title: str
    reason: str
    caption_suggestion: str
    score: float
    factors: dict[str, Any]
    category: str | None
    created_at: datetime


class HighlightRequest(APIModel):
    asset_id: uuid.UUID | None = None
    count: int = Field(default=5, ge=1, le=12)
    min_seconds: float = Field(default=20, ge=5, le=300)
    max_seconds: float = Field(default=60, ge=10, le=600)
    platform: str | None = None


class ShortsRequest(APIModel):
    count: int = Field(default=3, ge=1, le=10)
    duration: Literal[15, 30, 45, 60, 90] = 45
    platform: str | None = None
    asset_id: uuid.UUID | None = None
    highlight_ids: list[uuid.UUID] | None = None
    caption_preset: str = "bold"
    reframe: bool = True
    auto_render: bool = False
    render_preset: str | None = (
        None  # defaults to the platform preset (youtube_shorts | instagram_reel | tiktok)
    )


class ThumbnailCandidateOut(APIModel):
    asset_id: uuid.UUID
    time: float
    score: float
    factors: dict[str, Any]
    face: dict[str, Any] | None = None
    url: str


class ThumbnailsOut(APIModel):
    source_asset_id: uuid.UUID | None
    candidates: list[ThumbnailCandidateOut]


class BrollMatchOut(APIModel):
    asset_id: uuid.UUID
    filename: str
    score: float
    duration: float | None
    media_type: str
    reason: str


class BrollResolveResult(APIModel):
    placed: list[dict[str, Any]]
    unresolved: list[dict[str, Any]]
    state: dict[str, Any] | None = None


class BrollPlaceRequest(APIModel):
    marker_id: str
    asset_id: uuid.UUID
    duration: float | None = None
    timeline_id: uuid.UUID | None = None


class MulticamSyncRequest(APIModel):
    reference_asset_id: uuid.UUID
    asset_ids: list[uuid.UUID] = Field(min_length=1, max_length=8)
    place_on_timeline: bool = False
    timeline_id: uuid.UUID | None = None


class MulticamSyncOut(APIModel):
    reference_asset_id: uuid.UUID
    offsets: list[dict[str, Any]]
    state: dict[str, Any] | None = None


class SequenceSettingsUpdate(APIModel):
    caption_style: dict[str, Any] | None = None
    audio: dict[str, Any] | None = None
    aspect_ratio: str | None = None
    reframe_mode: Literal["center", "track", "off"] | None = None
    timeline_id: uuid.UUID | None = None

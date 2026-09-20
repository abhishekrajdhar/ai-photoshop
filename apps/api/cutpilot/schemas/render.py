from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from cutpilot.schemas.common import APIModel


class PresetOut(APIModel):
    id: str
    name: str
    description: str
    width: int
    height: int
    fps: float | None
    video_bitrate: str
    audio_bitrate: str
    codec: str
    aspect_ratio: str


class RenderRequest(APIModel):
    preset: str = "youtube_1080p"
    timeline_id: uuid.UUID | None = None
    kind: Literal["final", "preview"] = "final"
    settings: dict[str, Any] = Field(
        default_factory=dict
    )  # width/height/fps/video_bitrate/audio_bitrate/codec/aspect_ratio/filename


class RenderOut(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    timeline_version_id: uuid.UUID
    job_id: uuid.UUID | None
    kind: str
    status: str
    preset: str
    settings: dict[str, Any]
    output_asset_id: uuid.UUID | None
    duration: float | None
    error: str | None
    download_url: str | None = None
    stream_url: str | None = None
    created_at: datetime


class ExportRequest(APIModel):
    format: Literal["mp4", "srt", "vtt", "ass", "otio", "edl", "fcpxml"] = "mp4"
    preset: str = "youtube_1080p"
    timeline_id: uuid.UUID | None = None
    filename: str | None = Field(default=None, max_length=200)
    settings: dict[str, Any] = Field(default_factory=dict)


class ExportOut(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    render_id: uuid.UUID | None
    timeline_version_id: uuid.UUID | None
    job_id: uuid.UUID | None
    format: str
    preset: str
    filename: str
    status: str
    settings: dict[str, Any]
    output_asset_id: uuid.UUID | None
    size_bytes: int | None
    error: str | None
    download_url: str | None = None
    created_at: datetime

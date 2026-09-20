from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from cutpilot.schemas.common import APIModel


class MediaMetadataOut(APIModel):
    container: str | None
    video_codec: str | None
    audio_codec: str | None
    width: int | None
    height: int | None
    fps: float | None
    duration: float | None
    bitrate: int | None
    audio_channels: int | None
    sample_rate: int | None
    rotation: int


class AssetOut(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    parent_asset_id: uuid.UUID | None
    kind: str
    media_type: str
    filename: str
    mime_type: str
    size_bytes: int
    content_hash: str | None
    status: str
    error: str | None
    role: str | None
    extra: dict[str, Any]
    metadata: MediaMetadataOut | None = None
    proxy_asset_id: uuid.UUID | None = None
    audio_asset_id: uuid.UUID | None = None
    thumbnail_url: str | None = None
    stream_url: str = ""
    waveform_url: str | None = None
    created_at: datetime
    updated_at: datetime


class AssetUpdate(APIModel):
    filename: str | None = Field(default=None, min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=64)
    kind: str | None = None  # allow re-tagging original → broll | music | image


class UploadInitRequest(APIModel):
    filename: str = Field(min_length=1, max_length=512)
    mime_type: str = Field(default="application/octet-stream", max_length=128)
    size_bytes: int = Field(gt=0)
    client_hash: str | None = Field(default=None, min_length=64, max_length=64)
    kind: str = "original"  # original | broll | music | image
    role: str | None = None


class UploadInitResponse(APIModel):
    upload_id: uuid.UUID | None
    chunk_size: int
    total_chunks: int
    received_chunks: list[int]
    duplicate_of: AssetOut | None = None


class UploadStatusOut(APIModel):
    upload_id: uuid.UUID
    status: str
    received_chunks: list[int]
    total_chunks: int
    asset_id: uuid.UUID | None


class UploadCompleteResponse(APIModel):
    asset: AssetOut
    job_id: uuid.UUID

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from cutpilot.schemas.common import APIModel


class TranscriptWordOut(APIModel):
    id: uuid.UUID
    index: int
    start: float
    end: float
    text: str
    confidence: float | None
    speaker_id: uuid.UUID | None
    is_filler: bool


class TranscriptSegmentOut(APIModel):
    id: uuid.UUID
    index: int
    start: float
    end: float
    text: str
    speaker_id: uuid.UUID | None
    confidence: float | None
    words: list[TranscriptWordOut] = Field(default_factory=list)


class SpeakerOut(APIModel):
    id: uuid.UUID
    label: str
    display_name: str
    color: str | None


class TranscriptOut(APIModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    provider: str
    model: str
    language: str | None
    text: str
    confidence: float | None
    segments: list[TranscriptSegmentOut]
    speakers: list[SpeakerOut]
    created_at: datetime


class SegmentTextUpdate(APIModel):
    text: str = Field(max_length=5000)


class WordUpdate(APIModel):
    text: str | None = Field(default=None, max_length=128)
    is_filler: bool | None = None


class SpeakerUpdate(APIModel):
    display_name: str = Field(min_length=1, max_length=120)
    color: str | None = Field(default=None, max_length=16)


AnalysisStep = Literal[
    "transcription", "audio", "scenes", "content", "vision", "highlights", "thumbnails"
]


class AnalyzeRequest(APIModel):
    asset_id: uuid.UUID | None = None
    steps: list[AnalysisStep] = Field(
        default_factory=lambda: ["transcription", "audio", "scenes", "content", "vision"]
    )
    language: str | None = None
    force: bool = False


class AnalyzeResponse(APIModel):
    jobs: list[dict[str, Any]]


class SceneOut(APIModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    index: int
    start: float
    end: float
    thumbnail_url: str | None
    description: str | None
    labels: dict[str, Any]


class AnalysisResultOut(APIModel):
    id: uuid.UUID
    asset_id: uuid.UUID | None
    kind: str
    provider: str | None
    model: str | None
    data: dict[str, Any]
    created_at: datetime


class AIStatusOut(APIModel):
    preferred: str
    fallback: str | None
    available: list[str]
    configured: bool
    models: dict[str, Any]
    transcription: dict[str, Any]

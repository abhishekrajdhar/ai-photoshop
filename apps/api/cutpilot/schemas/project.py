from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from cutpilot.schemas.common import APIModel

TargetPlatform = Literal[
    "youtube",
    "instagram_reels",
    "youtube_shorts",
    "tiktok",
    "podcast",
    "linkedin",
    "twitter",
    "generic",
]


class ProjectSettings(APIModel):
    target_platform: TargetPlatform = "youtube"
    aspect_ratio: str = "16:9"
    fps: float | None = None
    filler_words: list[str] | None = None
    silence_threshold_db: float = -35.0
    silence_min_duration: float = 0.8
    caption_style: dict[str, object] = Field(default_factory=dict)


class ProjectCreate(APIModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    settings: ProjectSettings = Field(default_factory=ProjectSettings)


class ProjectUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    settings: ProjectSettings | None = None
    status: Literal["active", "archived"] | None = None


class ProjectOut(APIModel):
    id: uuid.UUID
    name: str
    description: str
    status: str
    settings: dict[str, object]
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    asset_count: int = 0
    thumbnail_url: str | None = None

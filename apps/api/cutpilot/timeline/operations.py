"""Strict schema for edit operations (the Edit Decision List).

Every operation carries: id, type, affected clip/asset, timestamps, parameters,
confidence, reason, source and a reversible flag. AI output is validated against
this schema before anything touches the timeline.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

OperationType = Literal[
    "cut",
    "split",
    "trim",
    "remove_segment",
    "delete_clip",
    "merge",
    "reorder",
    "move_clip",
    "speed_change",
    "jump_cut",
    "transition",
    "zoom",
    "crop",
    "reframe",
    "caption",
    "subtitle",
    "text_overlay",
    "image_overlay",
    "insert_broll",
    "insert_image",
    "insert_audio",
    "music",
    "audio_gain",
    "mute",
    "noise_reduction",
    "voice_enhancement",
    "normalize_audio",
    "fade_audio",
    "fade_video",
    "blur",
    "object_blur",
    "face_blur",
    "color_adjustment",
    "brightness",
    "contrast",
    "saturation",
    "lut",
    "stabilization",
    "filler_word_removal",
    "silence_removal",
    "set_track_state",
    "add_marker",
]

TimeRef = Literal["source", "timeline"]
OpSource = Literal["ai", "user", "system"]


class EditOperation(BaseModel):
    """One structured, reversible edit decision."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: f"op_{uuid.uuid4().hex[:12]}")
    type: OperationType
    # Target. AI operations usually target an asset in *source* time (transcript/scene time);
    # UI operations target a clip in *timeline* time.
    asset_id: str | None = None
    source_clip_id: str | None = Field(default=None, description="Timeline clip id when known")
    track_id: str | None = None
    time_ref: TimeRef = "source"
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, ge=0)
    timestamp: float | None = Field(default=None, ge=0)
    duration: float | None = Field(default=None, ge=0)
    # Batch ranges for silence/filler removal: [{"start":..,"end":..,"label":..}]
    segments: list[dict[str, Any]] | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    text: str | None = None
    query: str | None = None
    scale: float | None = Field(default=None, gt=0, le=4)
    confidence: float = Field(default=1.0, ge=0, le=1)
    reason: str = ""
    source: OpSource = "user"
    reversible: bool = True

    @model_validator(mode="after")
    def _check_times(self) -> EditOperation:
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("end must be >= start")
        range_ops = {
            "remove_segment",
            "jump_cut",
            "caption",
            "subtitle",
            "text_overlay",
            "speed_change",
            "audio_gain",
        }
        if (
            self.type in range_ops
            and self.segments is None
            and (self.start is None or self.end is None)
        ):
            raise ValueError(f"{self.type} requires start and end")
        if self.type in {
            "zoom",
            "insert_broll",
            "insert_image",
            "image_overlay",
            "insert_audio",
            "music",
        }:
            if self.timestamp is None and self.start is None:
                raise ValueError(f"{self.type} requires timestamp")
        if self.type in {"caption", "subtitle", "text_overlay"} and not self.text:
            raise ValueError(f"{self.type} requires text")
        if self.type in {"cut", "split"} and self.timestamp is None:
            raise ValueError(f"{self.type} requires timestamp")
        if self.type in {"filler_word_removal", "silence_removal"} and not self.segments:
            raise ValueError(f"{self.type} requires segments")
        return self

    def effective_start(self) -> float:
        if self.start is not None:
            return self.start
        return self.timestamp or 0.0

    def effective_end(self) -> float:
        if self.end is not None:
            return self.end
        return self.effective_start() + (self.duration or 0.0)


class EditDecisionList(BaseModel):
    """Planner output: a batch of operations plus a human-readable summary."""

    model_config = ConfigDict(extra="forbid")

    project_id: str | None = None
    timeline_version: int | None = None
    summary: str = Field(default="", description="What the edit does, in plain language")
    operations: list[EditOperation] = Field(default_factory=list)
    estimated_duration_delta: float | None = Field(
        default=None,
        description="Estimated change in timeline duration in seconds (negative = shorter)",
    )
    warnings: list[str] = Field(default_factory=list)


def edl_json_schema() -> dict[str, Any]:
    return EditDecisionList.model_json_schema()

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from cutpilot.schemas.common import APIModel
from cutpilot.timeline.operations import EditOperation


class TimelineOut(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    kind: str
    is_primary: bool
    current_version_id: uuid.UUID | None
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TimelineVersionOut(APIModel):
    id: uuid.UUID
    timeline_id: uuid.UUID
    version: int
    parent_version_id: uuid.UUID | None
    label: str
    source: str
    duration: float
    created_at: datetime
    operation_count: int = 0


class TimelineStateOut(APIModel):
    timeline: TimelineOut
    version: TimelineVersionOut
    document: dict[str, Any]
    can_undo: bool
    can_redo: bool


class SaveTimelineRequest(APIModel):
    document: dict[str, Any]
    label: str = Field(default="Manual edit", max_length=200)
    base_version_id: uuid.UUID | None = None


class ApplyOperationsRequest(APIModel):
    operations: list[EditOperation]
    label: str = Field(default="Edit", max_length=200)
    source: str = "user"


class ApplyOperationsResponse(APIModel):
    state: TimelineStateOut
    applied: list[EditOperation]
    rejected: list[dict[str, Any]]
    duration_before: float
    duration_after: float


class TimelineCreateRequest(APIModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = "alternate"
    from_version_id: uuid.UUID | None = None


class VersionCompareOut(APIModel):
    a: TimelineVersionOut
    b: TimelineVersionOut
    duration_delta: float
    added_clips: list[dict[str, Any]]
    removed_clips: list[dict[str, Any]]
    changed_clips: list[dict[str, Any]]

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from cutpilot.schemas.common import APIModel
from cutpilot.schemas.timeline import TimelineStateOut


class ChatMessageOut(APIModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    proposal: dict[str, Any] | None
    tool_calls: list[Any]
    job_id: uuid.UUID | None
    created_at: datetime


class ChatSessionOut(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    created_at: datetime
    messages: list[ChatMessageOut] = Field(default_factory=list)


class ChatSendRequest(APIModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    timeline_id: uuid.UUID | None = None


class ChatSendResponse(APIModel):
    session: ChatSessionOut
    user_message: ChatMessageOut
    assistant_message: ChatMessageOut
    job_id: uuid.UUID


class EditRequest(APIModel):
    instruction: str = Field(min_length=1, max_length=4000)
    target_platform: str | None = None
    target_duration_seconds: float | None = Field(default=None, gt=0)
    asset_id: uuid.UUID | None = None
    timeline_id: uuid.UUID | None = None


class ProposalPreviewOut(APIModel):
    document: dict[str, Any]
    duration_before: float
    duration_after: float
    applied: int
    rejected: list[dict[str, Any]]
    removed_ranges: list[dict[str, float]]


class ProposalApplyOut(APIModel):
    state: TimelineStateOut
    message: ChatMessageOut
    jobs: list[dict[str, Any]] = Field(default_factory=list)

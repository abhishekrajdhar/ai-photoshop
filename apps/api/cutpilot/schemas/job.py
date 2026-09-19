from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from cutpilot.schemas.common import APIModel


class JobOut(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    type: str
    status: str
    progress: float
    message: str
    error: str | None
    retry_count: int
    max_retries: int
    meta: dict[str, Any]
    result: dict[str, Any]
    queued_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

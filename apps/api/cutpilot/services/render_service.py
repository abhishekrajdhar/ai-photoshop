"""Render/export orchestration (implemented in Phase 6)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from cutpilot.core.errors import ValidationFailed
from cutpilot.db.models import Job, Project, Render, User


async def start_render(
    db: AsyncSession,
    *,
    project: Project,
    user: User,
    timeline_id: uuid.UUID,
    preset: str,
    settings: dict[str, Any],
) -> tuple[Render, Job]:
    raise ValidationFailed("Rendering is not available yet")

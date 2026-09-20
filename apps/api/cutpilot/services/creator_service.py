"""Creator features orchestration: Shorts, highlights, thumbnails (implemented in Phase 7)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from cutpilot.core.errors import ValidationFailed
from cutpilot.db.models import Job, Project, User


async def start_short_generation(
    db: AsyncSession,
    *,
    project: Project,
    user: User,
    count: int,
    duration: int,
    platform: str | None,
) -> Job:
    raise ValidationFailed("Short generation is not available yet")

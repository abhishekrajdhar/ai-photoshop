"""FastAPI dependencies: settings, DB session, current user, project ownership, rate limits."""

from __future__ import annotations

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cutpilot.core.config import Settings, get_settings
from cutpilot.core.constants import ACCESS_COOKIE
from cutpilot.core.errors import ForbiddenError, NotFoundError, RateLimited, UnauthorizedError
from cutpilot.core.security import decode_token
from cutpilot.db.models import Project, User
from cutpilot.db.session import get_db_session
from cutpilot.services.rate_limit import RateLimiter, get_rate_limiter

SettingsDep = Annotated[Settings, Depends(get_settings)]
DBSession = Annotated[AsyncSession, Depends(get_db_session)]


def _extract_token(request: Request, authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.cookies.get(ACCESS_COOKIE)


async def get_current_user(
    request: Request,
    db: DBSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    token = _extract_token(request, authorization)
    if not token:
        raise UnauthorizedError("Authentication required")
    try:
        payload = decode_token(token, "access")
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise UnauthorizedError("Invalid or expired token") from exc
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("User not found")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_owned_project(project_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Project:
    """Load a project and verify the caller owns it. Every project route must use this."""
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise NotFoundError("Project not found")
    if project.owner_id != user.id:
        raise ForbiddenError("You do not have access to this project")
    return project


OwnedProject = Annotated[Project, Depends(get_owned_project)]


async def rate_limit(
    request: Request,
    settings: SettingsDep,
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    client = request.client.host if request.client else "unknown"
    if not await limiter.allow(f"rl:{client}", settings.rate_limit_per_minute, 60):
        raise RateLimited("Too many requests")


async def ai_rate_limit(
    user: CurrentUser,
    settings: SettingsDep,
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    if not await limiter.allow(f"rl:ai:{user.id}", settings.ai_rate_limit_per_minute, 60):
        raise RateLimited("AI request limit reached, try again in a minute")

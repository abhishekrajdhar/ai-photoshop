"""User registration, login, password reset."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cutpilot.core.errors import ConflictError, UnauthorizedError, ValidationFailed
from cutpilot.core.logging import get_logger
from cutpilot.core.security import hash_password, verify_password
from cutpilot.db.models import PasswordResetToken, User

log = get_logger(__name__)


async def register_user(db: AsyncSession, *, email: str, password: str, display_name: str) -> User:
    email = email.strip().lower()
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("An account with this email already exists")
    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name.strip() or email.split("@")[0],
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    log.info("user_registered", user_id=str(user.id))
    return user


async def authenticate(db: AsyncSession, *, email: str, password: str) -> User:
    email = email.strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        raise UnauthorizedError("Invalid email or password")
    if not user.is_active:
        raise UnauthorizedError("Account disabled")
    user.last_login_at = datetime.now(UTC)
    await db.commit()
    return user


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_password_reset(db: AsyncSession, *, email: str) -> str | None:
    """Create a reset token. Returns the raw token (caller decides how to deliver it)."""
    user = (
        await db.execute(select(User).where(User.email == email.strip().lower()))
    ).scalar_one_or_none()
    if user is None:
        return None
    raw = secrets.token_urlsafe(32)
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_token(raw),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db.commit()
    return raw


async def confirm_password_reset(db: AsyncSession, *, token: str, password: str) -> User:
    row = (
        await db.execute(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == _hash_token(token))
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None or row.used_at is not None or row.expires_at.replace(tzinfo=UTC) < now:
        raise ValidationFailed("Reset token is invalid or expired")
    user = await db.get(User, row.user_id)
    if user is None:
        raise ValidationFailed("Reset token is invalid or expired")
    user.password_hash = hash_password(password)
    row.used_at = now
    await db.commit()
    return user


async def change_password(db: AsyncSession, user: User, *, current: str, new: str) -> None:
    if not verify_password(current, user.password_hash):
        raise UnauthorizedError("Current password is incorrect")
    user.password_hash = hash_password(new)
    await db.commit()


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)

"""Password hashing and JWT helpers."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from cutpilot.core.config import get_settings

_hasher = PasswordHasher()

TokenType = Literal["access", "refresh", "reset"]


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:  # malformed hash
        return False


def create_token(subject: uuid.UUID, token_type: TokenType, ttl: timedelta, **extra: Any) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": secrets.token_hex(8),
        **extra,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_access_token(user_id: uuid.UUID) -> str:
    return create_token(
        user_id, "access", timedelta(minutes=get_settings().access_token_ttl_minutes)
    )


def create_refresh_token(user_id: uuid.UUID) -> str:
    return create_token(user_id, "refresh", timedelta(days=get_settings().refresh_token_ttl_days))


def create_reset_token(user_id: uuid.UUID) -> str:
    return create_token(user_id, "reset", timedelta(hours=1))


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """Decode and validate a token. Raises jwt.PyJWTError on failure."""
    payload: dict[str, Any] = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return payload

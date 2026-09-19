from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field

from cutpilot.schemas.common import APIModel


class RegisterRequest(APIModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=120)


class LoginRequest(APIModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class PasswordResetRequest(APIModel):
    email: EmailStr


class PasswordResetConfirm(APIModel):
    token: str
    password: str = Field(min_length=8, max_length=128)


class ChangePasswordRequest(APIModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class UpdateProfileRequest(APIModel):
    display_name: str | None = Field(default=None, max_length=120)
    settings: dict[str, object] | None = None


class UserOut(APIModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    settings: dict[str, object]
    created_at: datetime


class AuthResponse(APIModel):
    user: UserOut
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class PasswordResetIssued(APIModel):
    ok: bool = True
    # Only populated in non-production environments (no email provider configured).
    dev_reset_token: str | None = None

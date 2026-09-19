from __future__ import annotations

import uuid

import jwt
from fastapi import APIRouter, Depends, Request, Response

from cutpilot.api.deps import CurrentUser, DBSession, SettingsDep, rate_limit
from cutpilot.core.constants import ACCESS_COOKIE, REFRESH_COOKIE
from cutpilot.core.errors import UnauthorizedError
from cutpilot.core.logging import get_logger
from cutpilot.core.security import create_access_token, create_refresh_token, decode_token
from cutpilot.db.models import User
from cutpilot.schemas.auth import (
    AuthResponse,
    ChangePasswordRequest,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetIssued,
    PasswordResetRequest,
    RegisterRequest,
    UpdateProfileRequest,
    UserOut,
)
from cutpilot.schemas.common import OkResponse
from cutpilot.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(rate_limit)])
log = get_logger(__name__)


def _set_auth_cookies(response: Response, user: User, settings) -> AuthResponse:  # type: ignore[no-untyped-def]
    access = create_access_token(user.id)
    refresh = create_refresh_token(user.id)
    common = {"httponly": True, "samesite": "lax", "secure": settings.cookie_secure, "path": "/"}
    response.set_cookie(
        ACCESS_COOKIE, access, max_age=settings.access_token_ttl_minutes * 60, **common
    )
    response.set_cookie(
        REFRESH_COOKIE, refresh, max_age=settings.refresh_token_ttl_days * 86400, **common
    )
    return AuthResponse(
        user=UserOut.model_validate(user),
        access_token=access,
        expires_in=settings.access_token_ttl_minutes * 60,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(
    body: RegisterRequest, response: Response, db: DBSession, settings: SettingsDep
) -> AuthResponse:
    user = await auth_service.register_user(
        db, email=body.email, password=body.password, display_name=body.display_name
    )
    return _set_auth_cookies(response, user, settings)


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest, response: Response, db: DBSession, settings: SettingsDep
) -> AuthResponse:
    user = await auth_service.authenticate(db, email=body.email, password=body.password)
    return _set_auth_cookies(response, user, settings)


@router.post("/refresh", response_model=AuthResponse)
async def refresh(
    request: Request, response: Response, db: DBSession, settings: SettingsDep
) -> AuthResponse:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise UnauthorizedError("No refresh token")
    try:
        payload = decode_token(token, "refresh")
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        _clear_auth_cookies(response)
        raise UnauthorizedError("Invalid refresh token") from exc
    user = await auth_service.get_user(db, user_id)
    if user is None or not user.is_active:
        _clear_auth_cookies(response)
        raise UnauthorizedError("User not found")
    return _set_auth_cookies(response, user, settings)


@router.post("/logout", response_model=OkResponse)
async def logout(response: Response) -> OkResponse:
    _clear_auth_cookies(response)
    return OkResponse()


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut)
async def update_me(body: UpdateProfileRequest, user: CurrentUser, db: DBSession) -> UserOut:
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
    if body.settings is not None:
        user.settings = {**user.settings, **body.settings}
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.post("/change-password", response_model=OkResponse)
async def change_password(
    body: ChangePasswordRequest, user: CurrentUser, db: DBSession
) -> OkResponse:
    await auth_service.change_password(
        db, user, current=body.current_password, new=body.new_password
    )
    return OkResponse()


@router.post("/password-reset/request", response_model=PasswordResetIssued)
async def request_password_reset(
    body: PasswordResetRequest, db: DBSession, settings: SettingsDep
) -> PasswordResetIssued:
    raw = await auth_service.issue_password_reset(db, email=body.email)
    # No outbound email provider is wired in; in development the token is returned so the
    # flow is testable end-to-end. In production it is only logged server-side.
    if raw is not None:
        log.info(
            "password_reset_issued",
            email=body.email,
            link=f"{settings.app_url}/reset-password?token={raw}",
        )
    return PasswordResetIssued(
        dev_reset_token=raw if (raw and not settings.is_production) else None
    )


@router.post("/password-reset/confirm", response_model=OkResponse)
async def confirm_password_reset(body: PasswordResetConfirm, db: DBSession) -> OkResponse:
    await auth_service.confirm_password_reset(db, token=body.token, password=body.password)
    return OkResponse()

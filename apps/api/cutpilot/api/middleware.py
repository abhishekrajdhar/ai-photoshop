"""CSRF, request-size and security-header middleware."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from cutpilot.core.constants import ACCESS_COOKIE, CSRF_HEADER

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class CSRFMiddleware(BaseHTTPMiddleware):
    """Cookie-authenticated mutating requests must carry a custom header.

    Browsers cannot add custom headers cross-site without a CORS preflight, which
    combined with SameSite=Lax cookies blocks CSRF. Bearer-token clients are exempt.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in SAFE_METHODS and ACCESS_COOKIE in request.cookies:
            if (
                not request.headers.get("authorization")
                and request.headers.get(CSRF_HEADER) is None
            ):
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": {"code": "csrf", "message": "Missing CSRF header", "details": {}}
                    },
                )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > self.max_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "payload_too_large",
                        "message": "Request body too large",
                        "details": {},
                    }
                },
            )
        return await call_next(request)

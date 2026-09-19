"""Application error types mapped to HTTP responses by the API layer."""

from __future__ import annotations


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(
        self, message: str = "Internal error", *, details: dict[str, object] | None = None
    ):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class AIConfigurationError(AppError):
    status_code = 503
    code = "ai_not_configured"


class AIProviderError(AppError):
    status_code = 502
    code = "ai_provider_error"


class MediaProcessingError(AppError):
    status_code = 500
    code = "media_processing_error"

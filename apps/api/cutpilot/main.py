"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cutpilot.api.errors import register_error_handlers
from cutpilot.api.middleware import (
    CSRFMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from cutpilot.api.router import api_router
from cutpilot.core.config import get_settings
from cutpilot.core.constants import API_TITLE, API_VERSION, PRODUCT_NAME
from cutpilot.core.logging import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.is_production)
    log.info(
        "api_starting",
        product=PRODUCT_NAME,
        env=settings.app_env,
        storage=settings.storage_provider,
        ai_provider=settings.ai_provider,
    )
    yield
    log.info("api_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    # Middleware (outermost first)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CSRFMiddleware)
    # Upload chunks are bounded by UPLOAD_CHUNK_SIZE; give some headroom for multipart framing.
    app.add_middleware(
        RequestSizeLimitMiddleware, max_bytes=max(settings.upload_chunk_size * 2, 32 * 1024 * 1024)
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.app_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(api_router)

    return app


app = create_app()

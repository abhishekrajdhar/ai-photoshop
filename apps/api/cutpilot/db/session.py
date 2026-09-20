"""Engine and session factories (async for the API, sync for workers/alembic)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from cutpilot.core.config import get_settings


def _schema_options() -> dict[str, object]:
    """Route every table to DB_SCHEMA (when set) without hard-coding schemas on the models."""
    schema = get_settings().db_schema
    return {"schema_translate_map": {None: schema}} if schema else {}


@lru_cache
def get_async_engine() -> AsyncEngine:
    settings = get_settings()
    url = settings.async_database_url
    kwargs: dict[str, object] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs = {}
    if _schema_options():
        kwargs["execution_options"] = _schema_options()
    return create_async_engine(url, **kwargs)


@lru_cache
def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_async_engine(), expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session."""
    async with get_async_session_factory()() as session:
        yield session


@lru_cache
def get_sync_engine():  # type: ignore[no-untyped-def]
    settings = get_settings()
    url = settings.sync_database_url
    kwargs: dict[str, object] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs = {}
    if _schema_options():
        kwargs["execution_options"] = _schema_options()
    return create_engine(url, **kwargs)


@lru_cache
def get_sync_session_factory() -> sessionmaker[Session]:
    return sessionmaker(get_sync_engine(), expire_on_commit=False)

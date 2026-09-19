"""Real-time event bus: workers publish to Redis pub/sub, the API streams via SSE."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import redis as redis_sync
from redis.asyncio import Redis

from cutpilot.core.config import get_settings
from cutpilot.core.logging import get_logger

log = get_logger(__name__)


def channel_for_project(project_id: uuid.UUID | str) -> str:
    return f"events:project:{project_id}"


def channel_for_user(user_id: uuid.UUID | str) -> str:
    return f"events:user:{user_id}"


def _payload(event: str, data: dict[str, Any]) -> str:
    return json.dumps(
        {"event": event, "data": data, "ts": datetime.now(UTC).isoformat()}, default=str
    )


class SyncEventPublisher:
    """Used inside Celery workers (synchronous)."""

    def __init__(self) -> None:
        self._client: redis_sync.Redis | None = None

    @property
    def client(self) -> redis_sync.Redis:
        if self._client is None:
            self._client = redis_sync.Redis.from_url(get_settings().redis_url)
        return self._client

    def publish(
        self,
        event: str,
        data: dict[str, Any],
        *,
        project_id: uuid.UUID | str | None = None,
        user_id: uuid.UUID | str | None = None,
    ) -> None:
        msg = _payload(event, data)
        try:
            if project_id is not None:
                self.client.publish(channel_for_project(project_id), msg)
            if user_id is not None:
                self.client.publish(channel_for_user(user_id), msg)
        except Exception as exc:  # events are best-effort
            log.warning("event_publish_failed", error=str(exc), event=event)


sync_publisher = SyncEventPublisher()


async def publish_async(
    event: str,
    data: dict[str, Any],
    *,
    project_id: uuid.UUID | str | None = None,
    user_id: uuid.UUID | str | None = None,
) -> None:
    settings = get_settings()
    if settings.app_env == "test":
        return
    client = Redis.from_url(settings.redis_url)
    try:
        msg = _payload(event, data)
        if project_id is not None:
            await client.publish(channel_for_project(project_id), msg)
        if user_id is not None:
            await client.publish(channel_for_user(user_id), msg)
    except Exception as exc:
        log.warning("event_publish_failed", error=str(exc), event=event)
    finally:
        await client.aclose()


async def subscribe(
    channels: list[str], *, heartbeat_seconds: float = 15.0
) -> AsyncIterator[dict[str, Any]]:
    """Yield SSE-ready dicts for messages on the given channels, with heartbeats."""
    client = Redis.from_url(get_settings().redis_url)
    pubsub = client.pubsub()
    await pubsub.subscribe(*channels)
    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                    timeout=heartbeat_seconds,
                )
            except TimeoutError:
                yield {"event": "heartbeat", "data": "{}"}
                continue
            if message is None:
                await asyncio.sleep(0.05)
                continue
            raw = message.get("data")
            if isinstance(raw, bytes):
                raw = raw.decode()
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                continue
            yield {"event": parsed.get("event", "message"), "data": json.dumps(parsed)}
    finally:
        await pubsub.unsubscribe(*channels)
        await pubsub.aclose()
        await client.aclose()

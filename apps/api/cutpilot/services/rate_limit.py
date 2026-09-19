"""Sliding-window rate limiter backed by Redis, with an in-memory fallback for tests."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from functools import lru_cache

from redis.asyncio import Redis

from cutpilot.core.config import get_settings


class RateLimiter:
    def __init__(self, redis: Redis | None):
        self._redis = redis
        self._memory: dict[str, deque[float]] = defaultdict(deque)

    async def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        if self._redis is None:
            bucket = self._memory[key]
            while bucket and bucket[0] < now - window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True
        try:
            pipe = self._redis.pipeline()
            pipe.zremrangebyscore(key, 0, now - window_seconds)
            pipe.zadd(key, {f"{now}": now})
            pipe.zcard(key)
            pipe.expire(key, window_seconds)
            _, _, count, _ = await pipe.execute()
            return int(count) <= limit
        except Exception:
            # Redis unavailable: fail open so the product stays usable.
            return True


@lru_cache
def get_rate_limiter() -> RateLimiter:
    settings = get_settings()
    if settings.app_env == "test":
        return RateLimiter(None)
    return RateLimiter(Redis.from_url(settings.redis_url, decode_responses=True))

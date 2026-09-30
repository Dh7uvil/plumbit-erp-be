"""Sliding-window rate limiter for sensitive auth endpoints."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from threading import Lock
from typing import Protocol

from fastapi import Request

from app.core.config import get_settings
from app.core.exceptions import RateLimitExceededError
from app.core.middleware import get_client_ip


class RateLimiter(Protocol):
    def hit(self, key: str, *, limit: int, window_seconds: int) -> bool:
        """Record a hit and return True when it is within the limit."""

    def reset(self) -> None:
        """Clear all counters (used in tests)."""


class SlidingWindowLimiter:
    """Count hits per key inside a rolling window. Process-local only."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._hits: dict[str, list[float]] = defaultdict(list)

    def hit(self, key: str, *, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            timestamps = [stamp for stamp in self._hits[key] if stamp > cutoff]
            if len(timestamps) >= limit:
                self._hits[key] = timestamps
                return False
            timestamps.append(now)
            self._hits[key] = timestamps
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class RedisSlidingWindowLimiter:
    """Distributed sliding-window limiter backed by Redis sorted sets."""

    def __init__(self, redis_url: str) -> None:
        import redis

        self._client = redis.from_url(redis_url, decode_responses=True)

    def hit(self, key: str, *, limit: int, window_seconds: int) -> bool:
        now = time.time()
        redis_key = f"rate:{key}"
        cutoff = now - window_seconds
        member = f"{now}:{uuid.uuid4().hex}"
        pipe = self._client.pipeline()
        pipe.zremrangebyscore(redis_key, 0, cutoff)
        pipe.zcard(redis_key)
        results = pipe.execute()
        current_count = int(results[1])
        if current_count >= limit:
            return False
        pipe = self._client.pipeline()
        pipe.zadd(redis_key, {member: now})
        pipe.expire(redis_key, window_seconds)
        pipe.execute()
        return True

    def reset(self) -> None:
        for key in self._client.scan_iter("rate:*"):
            self._client.delete(key)


_auth_limiter: RateLimiter | None = None


def get_auth_limiter() -> RateLimiter:
    global _auth_limiter
    if _auth_limiter is None:
        settings = get_settings()
        if settings.redis_url:
            _auth_limiter = RedisSlidingWindowLimiter(settings.redis_url)
        else:
            _auth_limiter = auth_limiter
    return _auth_limiter


auth_limiter = SlidingWindowLimiter()


def client_key(request: Request) -> str:
    ip = get_client_ip()
    if ip:
        return ip
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def enforce_auth_rate_limit(key: str) -> None:
    """Reject the request when `auth_rate_limit_requests` is exceeded.

    Tests skip the limiter so unique-login fixtures do not trip an IP-wide cap.
    """

    settings = get_settings()
    if settings.env == "testing":
        return
    limiter = get_auth_limiter()
    allowed = limiter.hit(
        key,
        limit=settings.auth_rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    if not allowed:
        raise RateLimitExceededError()

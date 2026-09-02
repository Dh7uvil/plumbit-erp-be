"""In-process sliding-window rate limiter for sensitive auth endpoints."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock
from time import monotonic

from fastapi import Request

from app.core.config import get_settings
from app.core.exceptions import RateLimitExceededError
from app.core.middleware import get_client_ip


class SlidingWindowLimiter:
    """Count hits per key inside a rolling window. Process-local only."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._hits: dict[str, list[float]] = defaultdict(list)

    def hit(self, key: str, *, limit: int, window_seconds: int) -> bool:
        """Record a hit and return True when it is within the limit."""

        now = monotonic()
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
    allowed = auth_limiter.hit(
        key,
        limit=settings.auth_rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    if not allowed:
        raise RateLimitExceededError()

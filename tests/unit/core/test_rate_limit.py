"""Unit tests for the auth sliding-window limiter."""

import pytest

from app.core.exceptions import RateLimitExceededError
from app.core.rate_limit import SlidingWindowLimiter, auth_limiter, enforce_auth_rate_limit


def test_sliding_window_blocks_after_limit() -> None:
    limiter = SlidingWindowLimiter()
    assert limiter.hit("login", limit=2, window_seconds=60) is True
    assert limiter.hit("login", limit=2, window_seconds=60) is True
    assert limiter.hit("login", limit=2, window_seconds=60) is False
    assert limiter.hit("other", limit=2, window_seconds=60) is True


def test_enforce_auth_rate_limit_honors_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Settings:
        env = "development"
        auth_rate_limit_requests = 1
        rate_limit_window_seconds = 60

    monkeypatch.setattr("app.core.rate_limit.get_settings", lambda: _Settings())
    auth_limiter.reset()
    enforce_auth_rate_limit("login:test")
    with pytest.raises(RateLimitExceededError):
        enforce_auth_rate_limit("login:test")

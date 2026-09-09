"""Unit tests for outbox backoff scheduling."""

from datetime import UTC, datetime, timedelta

from app.common.outbox.service import next_available_at


def test_backoff_is_two_to_the_attempts() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert next_available_at(1, now=now) == now + timedelta(seconds=2)
    assert next_available_at(3, now=now) == now + timedelta(seconds=8)


def test_backoff_is_capped() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert next_available_at(20, now=now, cap_seconds=1024) == now + timedelta(seconds=1024)

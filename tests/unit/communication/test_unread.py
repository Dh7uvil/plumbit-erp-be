"""Unread math tests."""

from app.communication.shared.unread import unread_count


def test_unread_count_basic() -> None:
    assert unread_count(10, 7) == 3
    assert unread_count(5, 5) == 0
    assert unread_count(3, 10) == 0

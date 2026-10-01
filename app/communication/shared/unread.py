"""Unread count helpers."""

from __future__ import annotations


def unread_count(message_seq: int, last_read_seq: int) -> int:
    return max(0, int(message_seq) - int(last_read_seq))

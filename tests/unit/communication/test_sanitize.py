"""Sanitization and mention parsing tests."""

import pytest

from app.communication.messages.mentions import parse_mentions
from app.communication.shared.sanitize import sanitize_message_body
from app.core.exceptions import ValidationError


def test_sanitize_strips_control_chars() -> None:
    assert sanitize_message_body("hello\x00world") == "helloworld"


def test_sanitize_rejects_empty_body() -> None:
    with pytest.raises(ValidationError):
        sanitize_message_body("   \x00  ")


def test_parse_user_and_everyone_mentions() -> None:
    user_id = "550e8400-e29b-41d4-a716-446655440000"
    mentioned, is_everyone = parse_mentions(f"Hi @everyone and @{user_id}")
    assert is_everyone is True
    assert len(mentioned) == 1
    assert str(mentioned[0]) == user_id

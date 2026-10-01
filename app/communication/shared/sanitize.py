"""Message body sanitization for chat."""

from __future__ import annotations

import re

from app.core.exceptions import ValidationError

_MAX_MESSAGE_BODY_LENGTH = 10_000
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_message_body(body: str) -> str:
    """Strip control characters and enforce the chat message length cap."""

    cleaned = _CONTROL_CHAR_PATTERN.sub("", body).strip()
    if not cleaned:
        raise ValidationError("Message body cannot be empty")
    if len(cleaned) > _MAX_MESSAGE_BODY_LENGTH:
        raise ValidationError(
            f"Message body exceeds the maximum length of {_MAX_MESSAGE_BODY_LENGTH} characters",
            details={"max_length": _MAX_MESSAGE_BODY_LENGTH},
        )
    return cleaned

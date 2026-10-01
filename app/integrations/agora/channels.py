"""Deterministic Agora channel naming and charset validation."""

from __future__ import annotations

import re
from uuid import UUID

_CHANNEL_CHARSET = re.compile(r"^[a-zA-Z0-9 !#$%&()+,\-:;<=>?@\[\]^_{|}~.]+$")
_MAX_CHANNEL_LENGTH = 64


def _tenant_prefix(tenant_id: UUID) -> str:
    return tenant_id.hex[:8]


def conversation_channel_name(tenant_id: UUID, conversation_id: UUID) -> str:
    name = f"t{_tenant_prefix(tenant_id)}-c{conversation_id}"
    validate_channel_name(name)
    return name


def call_channel_name(tenant_id: UUID, call_id: UUID) -> str:
    name = f"t{_tenant_prefix(tenant_id)}-call-{call_id}"
    validate_channel_name(name)
    return name


def inbox_channel_name(user_id: UUID) -> str:
    name = f"u-{user_id}"
    validate_channel_name(name)
    return name


def presence_channel_name(tenant_id: UUID) -> str:
    name = f"t{_tenant_prefix(tenant_id)}-presence"
    validate_channel_name(name)
    return name


_CONVERSATION_CHANNEL_RE = re.compile(
    r"^t([0-9a-f]{8})-c([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)


def parse_conversation_channel(name: str) -> tuple[str, UUID] | None:
    """Return (tenant_prefix, conversation_id) when name is a conversation channel."""

    match = _CONVERSATION_CHANNEL_RE.match(name)
    if match is None:
        return None
    return match.group(1), UUID(match.group(2))


def validate_channel_name(name: str) -> None:
    if not name or len(name) > _MAX_CHANNEL_LENGTH:
        msg = f"channel name must be 1-{_MAX_CHANNEL_LENGTH} characters"
        raise ValueError(msg)
    if not _CHANNEL_CHARSET.fullmatch(name):
        raise ValueError("channel name contains invalid characters")

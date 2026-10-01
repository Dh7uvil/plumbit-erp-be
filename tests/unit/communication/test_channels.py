"""Channel naming tests."""

from uuid import UUID

import pytest

from app.integrations.agora.channels import (
    call_channel_name,
    conversation_channel_name,
    inbox_channel_name,
    presence_channel_name,
    validate_channel_name,
)

TENANT = UUID("11111111-1111-1111-1111-111111111111")
CONV = UUID("22222222-2222-2222-2222-222222222222")
CALL = UUID("33333333-3333-3333-3333-333333333333")
USER = UUID("44444444-4444-4444-4444-444444444444")


def test_conversation_channel_name() -> None:
    name = conversation_channel_name(TENANT, CONV)
    assert name.startswith("t11111111-c")
    assert len(name) <= 64
    validate_channel_name(name)


def test_call_channel_name() -> None:
    name = call_channel_name(TENANT, CALL)
    assert "call" in name
    validate_channel_name(name)


def test_inbox_and_presence_channels() -> None:
    validate_channel_name(inbox_channel_name(USER))
    validate_channel_name(presence_channel_name(TENANT))


def test_invalid_channel_name() -> None:
    with pytest.raises(ValueError):
        validate_channel_name("bad/channel")

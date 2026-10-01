"""Signaling publisher tests."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from app.core.config import get_settings
from app.communication.shared.signaling_publisher import (
    _channel_for_event,
    _resolve_signaling_sender,
    build_event,
    flush_pending_signaling,
    schedule_inbox_signaling_events,
    schedule_signaling_event,
)
from app.integrations.agora.channels import conversation_channel_name, inbox_channel_name
from app.integrations.agora.identity import format_agora_user_id
from app.integrations.agora.events import RealtimeEvent


class FailingSignalingClient:
    def __init__(self) -> None:
        self.attempts = 0

    async def publish(
        self,
        *,
        channel: str,
        sender_id: str,
        event: RealtimeEvent,
    ) -> None:
        self.attempts += 1
        raise RuntimeError("publish failed")


class SucceedingSignalingClient:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, RealtimeEvent]] = []

    async def publish(
        self,
        *,
        channel: str,
        sender_id: str,
        event: RealtimeEvent,
    ) -> None:
        self.events.append((channel, sender_id, event))


def _mock_session() -> SimpleNamespace:
    return SimpleNamespace(sync_session=SimpleNamespace(info={}))


@pytest.fixture(autouse=True)
def enable_communication(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEATURE_COMMUNICATION_ENABLED", "true")
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def stub_signaling_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    async def get_or_create_mapping(_self, tenant_id: UUID, user_id: UUID) -> SimpleNamespace:
        return SimpleNamespace(agora_user_id=format_agora_user_id(tenant_id, user_id))

    monkeypatch.setattr(
        "app.communication.shared.signaling_publisher.ChatIdentityService.get_or_create_mapping",
        get_or_create_mapping,
    )


@pytest.mark.asyncio
async def test_flush_pending_signaling_tolerates_publish_failure() -> None:
    tenant_id = UUID(int=1)
    user_id = UUID(int=2)
    event = build_event(
        event_type="call.invited",
        tenant_id=tenant_id,
        actor_id=user_id,
        conversation_id=UUID(int=3),
        data={"call_id": str(UUID(int=4)), "target_user_id": str(user_id)},
    )
    session = _mock_session()
    schedule_signaling_event(session, event)
    client = FailingSignalingClient()

    await flush_pending_signaling(session, client=client)

    assert client.attempts == 2


class _IdentityStub:
    async def get_or_create_mapping(self, tenant_id: UUID, user_id: UUID) -> SimpleNamespace:
        return SimpleNamespace(agora_user_id=format_agora_user_id(tenant_id, user_id))


@pytest.mark.asyncio
async def test_resolve_signaling_sender_uses_agora_user_id() -> None:
    tenant_id = UUID(int=1)
    user_id = UUID(int=2)
    event = build_event(
        event_type="message.created",
        tenant_id=tenant_id,
        actor_id=user_id,
        conversation_id=UUID(int=3),
    )
    cache: dict[tuple[UUID, UUID], str] = {}

    sender = await _resolve_signaling_sender(_IdentityStub(), event, cache)

    assert sender == format_agora_user_id(tenant_id, user_id)
    assert cache[(tenant_id, user_id)] == sender


@pytest.mark.asyncio
async def test_flush_pending_signaling_publishes_on_success() -> None:
    tenant_id = UUID(int=1)
    user_id = UUID(int=2)
    event = build_event(
        event_type="call.invited",
        tenant_id=tenant_id,
        actor_id=user_id,
        conversation_id=UUID(int=3),
        data={"call_id": str(UUID(int=4)), "target_user_id": str(user_id)},
    )
    session = _mock_session()
    schedule_signaling_event(session, event)
    client = SucceedingSignalingClient()

    await flush_pending_signaling(session, client=client)

    assert len(client.events) == 1
    assert client.events[0][2].type == "call.invited"


def test_channel_for_event_routes_read_receipts_to_inbox() -> None:
    tenant_id = UUID(int=1)
    reader_id = UUID(int=2)
    sender_id = UUID(int=3)
    conversation_id = UUID(int=4)
    event = build_event(
        event_type="message.read",
        tenant_id=tenant_id,
        actor_id=reader_id,
        conversation_id=conversation_id,
        seq=5,
        data={"user_id": str(reader_id), "up_to_seq": 5, "target_user_id": str(sender_id)},
    )

    assert _channel_for_event(event) == inbox_channel_name(sender_id)
    assert _channel_for_event(
        build_event(
            event_type="message.read",
            tenant_id=tenant_id,
            actor_id=reader_id,
            conversation_id=conversation_id,
            seq=5,
            data={"user_id": str(reader_id), "up_to_seq": 5},
        )
    ) == conversation_channel_name(tenant_id, conversation_id)


@pytest.mark.asyncio
async def test_flush_pending_signaling_publishes_concurrently() -> None:
    tenant_id = UUID(int=1)
    user_id = UUID(int=2)
    other_user_id = UUID(int=5)
    conversation_id = UUID(int=3)
    session = _mock_session()
    schedule_signaling_event(
        session,
        build_event(
            event_type="message.created",
            tenant_id=tenant_id,
            actor_id=user_id,
            conversation_id=conversation_id,
            seq=10,
            data={"id": str(UUID(int=6)), "body": "hello"},
        ),
    )
    schedule_signaling_event(
        session,
        build_event(
            event_type="message.created",
            tenant_id=tenant_id,
            actor_id=user_id,
            conversation_id=conversation_id,
            seq=10,
            data={
                "id": str(UUID(int=6)),
                "body": "hello",
                "target_user_id": str(other_user_id),
            },
        ),
    )
    client = SucceedingSignalingClient()

    await flush_pending_signaling(session, client=client)

    assert len(client.events) == 2
    channels = {channel for channel, _sender, _event in client.events}
    assert conversation_channel_name(tenant_id, conversation_id) in channels
    assert inbox_channel_name(other_user_id) in channels


@pytest.mark.asyncio
async def test_schedule_inbox_signaling_events_fanout() -> None:
    tenant_id = UUID(int=1)
    reader_id = UUID(int=2)
    sender_id = UUID(int=3)
    conversation_id = UUID(int=4)
    session = _mock_session()
    schedule_inbox_signaling_events(
        session,
        build_event(
            event_type="message.read",
            tenant_id=tenant_id,
            actor_id=reader_id,
            conversation_id=conversation_id,
            seq=5,
            data={"user_id": str(reader_id), "up_to_seq": 5},
        ),
        participant_user_ids=[reader_id, sender_id],
        actor_user_id=reader_id,
    )
    client = SucceedingSignalingClient()

    await flush_pending_signaling(session, client=client)

    assert len(client.events) == 2
    channels = {channel for channel, _sender, _event in client.events}
    assert conversation_channel_name(tenant_id, conversation_id) in channels
    assert inbox_channel_name(sender_id) in channels

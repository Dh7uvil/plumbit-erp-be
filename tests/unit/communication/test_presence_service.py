"""Presence service unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from app.communication.presence.schemas import HeartbeatRequest
from app.communication.presence.service import PresenceService
from app.core.config import get_settings
from app.core.enums import PresenceStatus
from app.integrations.agora.identity import format_agora_user_id
from app.integrations.realtime.client import get_redis_realtime_client, reset_redis_realtime_client_for_tests


def _mock_session() -> SimpleNamespace:
    return SimpleNamespace(sync_session=SimpleNamespace(info={}))


class _PresenceRepoStub:
    def __init__(self, existing: SimpleNamespace | None = None) -> None:
        self.existing = existing
        self.upsert_calls = 0

    async def get(self, _tenant_id: UUID, _user_id: UUID) -> SimpleNamespace | None:
        return self.existing

    async def upsert(self, tenant_id: UUID, user_id: UUID, values: dict) -> SimpleNamespace:
        self.upsert_calls += 1
        self.existing = SimpleNamespace(
            tenant_id=tenant_id,
            user_id=user_id,
            status=values["status"],
            custom_status=values.get("custom_status"),
            last_heartbeat_at=values["last_heartbeat_at"],
            last_seen_at=values["last_seen_at"],
        )
        return self.existing


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


@pytest.fixture(autouse=True)
def clear_signaling() -> None:
    reset_redis_realtime_client_for_tests()
    yield
    reset_redis_realtime_client_for_tests()


@pytest.fixture
def stub_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _transaction(_session):
        yield

    monkeypatch.setattr("app.communication.presence.service.transaction", _transaction)


@pytest.mark.asyncio
async def test_heartbeat_does_not_publish_when_status_unchanged(
    stub_transaction: None,
) -> None:
    tenant_id = UUID(int=1)
    user_id = UUID(int=2)
    existing = SimpleNamespace(
        tenant_id=tenant_id,
        user_id=user_id,
        status=PresenceStatus.ONLINE.value,
        custom_status=None,
        last_heartbeat_at=None,
        last_seen_at=None,
    )
    service = PresenceService(session=_mock_session())  # type: ignore[arg-type]
    service.repo = _PresenceRepoStub(existing=existing)

    await service.heartbeat(
        tenant_id,
        user_id,
        HeartbeatRequest(status=PresenceStatus.ONLINE, custom_status=None),
    )

    assert get_redis_realtime_client().events == []


@pytest.mark.asyncio
async def test_heartbeat_publishes_when_status_changes(stub_transaction: None) -> None:
    tenant_id = UUID(int=1)
    user_id = UUID(int=2)
    existing = SimpleNamespace(
        tenant_id=tenant_id,
        user_id=user_id,
        status=PresenceStatus.OFFLINE.value,
        custom_status=None,
        last_heartbeat_at=None,
        last_seen_at=None,
    )
    service = PresenceService(session=_mock_session())  # type: ignore[arg-type]
    service.repo = _PresenceRepoStub(existing=existing)

    await service.heartbeat(
        tenant_id,
        user_id,
        HeartbeatRequest(status=PresenceStatus.ONLINE, custom_status="In a meeting"),
    )

    published = get_redis_realtime_client().events
    assert len(published) == 1
    _channel, _sender, event = published[0]
    assert event.type == "presence.changed"
    assert event.data["status"] == PresenceStatus.ONLINE.value
    assert event.data["custom_status"] == "In a meeting"

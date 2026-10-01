"""Communication maintenance worker tests."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.common.utils.datetime import utcnow
from app.communication.shared.maintenance_worker import sweep_stale_presence
from app.core.enums import PresenceStatus
from app.integrations.realtime.presence import reset_presence_connection_store_for_tests


@pytest.mark.asyncio
async def test_sweep_stale_presence_marks_offline_when_not_in_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEATURE_COMMUNICATION_ENABLED", "true")
    reset_presence_connection_store_for_tests()

    tenant_id = UUID(int=1)
    user_id = UUID(int=2)
    stale_at = utcnow() - timedelta(seconds=300)
    row = SimpleNamespace(
        tenant_id=tenant_id,
        user_id=user_id,
        status=PresenceStatus.ONLINE.value,
        custom_status=None,
        last_heartbeat_at=stale_at,
        last_seen_at=None,
    )
    published: list[tuple] = []

    class _SessionStub:
        async def execute(self, _stmt):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [row]))

    class _SessionFactory:
        async def __aenter__(self):
            return _SessionStub()

        async def __aexit__(self, *_args):
            return None

    async def _flush(_session):
        return None

    def _schedule(_session, event):
        published.append(event)

    monkeypatch.setattr(
        "app.communication.shared.maintenance_worker.async_session_factory",
        lambda: _SessionFactory(),
    )
    monkeypatch.setattr(
        "app.communication.shared.maintenance_worker.transaction",
        lambda _session: _AsyncContext(),
    )
    monkeypatch.setattr(
        "app.communication.shared.maintenance_worker.schedule_signaling_event",
        _schedule,
    )
    monkeypatch.setattr(
        "app.communication.shared.maintenance_worker.flush_pending_signaling",
        _flush,
    )

    await sweep_stale_presence(120)

    assert row.status == PresenceStatus.OFFLINE.value
    assert len(published) == 1
    assert published[0].type == "presence.changed"


class _AsyncContext:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *_args):
        return None

"""Communication API test fixtures."""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.communication.realtime.connection_manager import reset_connection_manager_for_tests
from app.communication.realtime.tickets import clear_ws_tickets_for_tests
from app.integrations.realtime.bus import reset_realtime_bus_for_tests
from app.integrations.realtime.client import get_redis_realtime_client, reset_redis_realtime_client_for_tests


@pytest.fixture(autouse=True)
def enable_communication(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEATURE_COMMUNICATION_ENABLED", "true")
    monkeypatch.setenv(
        "AGORA_APP_ID",
        "01234567890123456789012345678901",
    )
    monkeypatch.setenv(
        "AGORA_APP_CERTIFICATE",
        "01234567890123456789012345678901",
    )
    reset_realtime_bus_for_tests()
    reset_redis_realtime_client_for_tests()
    reset_connection_manager_for_tests()
    clear_ws_tickets_for_tests()
    get_settings.cache_clear()


@pytest.fixture
def signaling_events():
    return get_redis_realtime_client().events


async def create_peer_user(
    client,
    headers: dict[str, str],
) -> tuple[str, str, str]:
    from uuid import uuid4

    roles = await client.get("/api/v1/roles", headers=headers)
    assert roles.status_code == 200, roles.text
    superadmin_id = next(
        item["id"] for item in roles.json()["data"] if item["name"] == "Superadmin"
    )
    suffix = uuid4().hex[:8]
    email = f"peer-{suffix}@example.com"
    password = "Password12"
    user = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "Peer User",
            "email": email,
            "password": password,
            "role_ids": [superadmin_id],
        },
    )
    assert user.status_code == 201, user.text
    user_id = user.json()["data"]["id"]
    return user_id, email, password

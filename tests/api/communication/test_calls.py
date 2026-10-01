"""Call API tests."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.common.utils.datetime import utcnow
from app.communication.calls.models import Call
from app.db.session import async_session_factory, transaction
from tests.api.communication.conftest import create_peer_user
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_call_lifecycle(client: AsyncClient, signaling_events) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    other_user_id, other_email, other_password = await create_peer_user(client, headers)
    other_headers = await login_headers(client, tenant_id, other_email, other_password)

    created = await client.post(
        "/api/v1/communication/calls",
        headers=headers,
        json={"user_id": other_user_id, "kind": "AUDIO"},
    )
    assert created.status_code == 201, created.text
    call = created.json()["data"]
    assert call["conversation_id"]
    assert call["status"] == "RINGING"
    assert any(e[2].type == "call.invited" for e in signaling_events)

    accepted = await client.post(
        f"/api/v1/communication/calls/{call['id']}/accept",
        headers=other_headers,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["status"] == "ACTIVE"

    ended = await client.post(
        f"/api/v1/communication/calls/{call['id']}/end",
        headers=headers,
    )
    assert ended.status_code == 200, ended.text
    assert ended.json()["data"]["status"] == "ENDED"


@pytest.mark.asyncio
async def test_cancel_ringing_call(client: AsyncClient, signaling_events) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    other_user_id, _, _ = await create_peer_user(client, headers)

    created = await client.post(
        "/api/v1/communication/calls",
        headers=headers,
        json={"user_id": other_user_id, "kind": "VIDEO"},
    )
    assert created.status_code == 201, created.text
    call = created.json()["data"]
    assert call["status"] == "RINGING"

    cancelled = await client.post(
        f"/api/v1/communication/calls/{call['id']}/end",
        headers=headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_call_invited_includes_caller_metadata(client: AsyncClient, signaling_events) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    other_user_id, _, _ = await create_peer_user(client, headers)

    created = await client.post(
        "/api/v1/communication/calls",
        headers=headers,
        json={"user_id": other_user_id, "kind": "AUDIO"},
    )
    assert created.status_code == 201, created.text

    invited = next(e for e in signaling_events if e[2].type == "call.invited")
    data = invited[2].data
    assert data["caller_name"]
    assert data["ring_timeout_seconds"] == 45
    assert data["target_user_id"] == other_user_id


@pytest.mark.asyncio
async def test_list_calls_mine_filter(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    other_user_id, other_email, other_password = await create_peer_user(client, headers)
    other_headers = await login_headers(client, tenant_id, other_email, other_password)
    third_user_id, third_email, third_password = await create_peer_user(client, headers)
    third_headers = await login_headers(client, tenant_id, third_email, third_password)

    created = await client.post(
        "/api/v1/communication/calls",
        headers=headers,
        json={"user_id": other_user_id, "kind": "AUDIO"},
    )
    assert created.status_code == 201, created.text
    call_id = created.json()["data"]["id"]

    me_response = await client.get("/api/v1/auth/me", headers=headers)
    assert me_response.status_code == 200, me_response.text
    admin_user_id = me_response.json()["data"]["id"]

    unrelated = await client.post(
        "/api/v1/communication/calls",
        headers=third_headers,
        json={"user_id": admin_user_id, "kind": "VIDEO"},
    )
    assert unrelated.status_code == 201, unrelated.text

    mine = await client.get(
        "/api/v1/communication/calls",
        headers=other_headers,
        params={"status": "RINGING", "mine": "true"},
    )
    assert mine.status_code == 200, mine.text
    ids = {row["id"] for row in mine.json()["data"]}
    assert call_id in ids
    assert unrelated.json()["data"]["id"] not in ids


@pytest.mark.asyncio
async def test_direct_leave_ends_call_for_both_participants(
    client: AsyncClient, signaling_events
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    other_user_id, other_email, other_password = await create_peer_user(client, headers)
    other_headers = await login_headers(client, tenant_id, other_email, other_password)

    created = await client.post(
        "/api/v1/communication/calls",
        headers=headers,
        json={"user_id": other_user_id, "kind": "AUDIO"},
    )
    assert created.status_code == 201, created.text
    call_id = created.json()["data"]["id"]

    accepted = await client.post(
        f"/api/v1/communication/calls/{call_id}/accept",
        headers=other_headers,
    )
    assert accepted.status_code == 200, accepted.text

    left = await client.post(
        f"/api/v1/communication/calls/{call_id}/leave",
        headers=other_headers,
    )
    assert left.status_code == 200, left.text
    assert left.json()["data"]["status"] == "ENDED"

    ended_events = [
        e for e in signaling_events if e[2].type == "call.ended" and e[2].data.get("call_id") == call_id
    ]
    assert len(ended_events) >= 2


@pytest.mark.asyncio
async def test_stale_ringing_call_expires_on_get(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    other_user_id, _, _ = await create_peer_user(client, headers)

    created = await client.post(
        "/api/v1/communication/calls",
        headers=headers,
        json={"user_id": other_user_id, "kind": "AUDIO"},
    )
    assert created.status_code == 201, created.text
    call_id = created.json()["data"]["id"]

    stale_started_at = utcnow() - timedelta(seconds=120)
    async with async_session_factory() as session, transaction(session):
        await session.execute(
            update(Call)
            .where(Call.id == UUID(call_id))
            .values(started_at=stale_started_at)
        )

    fetched = await client.get(
        f"/api/v1/communication/calls/{call_id}",
        headers=headers,
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["data"]["status"] == "MISSED"

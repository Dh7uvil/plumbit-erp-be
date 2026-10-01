"""Message API tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.communication.conftest import create_peer_user
from tests.conftest import login_headers, provision_admin


async def _direct_conversation(client: AsyncClient, headers: dict, other_user_id: str) -> str:
    response = await client.post(
        "/api/v1/communication/conversations",
        headers=headers,
        json={"kind": "DIRECT", "other_user_id": other_user_id},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


@pytest.mark.asyncio
async def test_message_lifecycle(client: AsyncClient, signaling_events) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    other_user_id, _, _ = await create_peer_user(client, headers)
    conv_id = await _direct_conversation(client, headers, other_user_id)

    created = await client.post(
        f"/api/v1/communication/conversations/{conv_id}/messages",
        headers=headers,
        json={"body": "Hello", "client_message_id": "c1"},
    )
    assert created.status_code == 201, created.text
    message = created.json()["data"]
    assert message["seq"] == 1
    assert any(e[2].type == "message.created" for e in signaling_events)

    listed = await client.get(
        f"/api/v1/communication/conversations/{conv_id}/messages",
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    listed_data = listed.json()["data"]
    assert len(listed_data["items"]) == 1
    assert listed_data["has_more"] is False
    assert listed.json()["meta"]["has_more"] is False

    updated = await client.patch(
        f"/api/v1/communication/messages/{message['id']}",
        headers=headers,
        json={"body": "Hello edited"},
    )
    assert updated.status_code == 200, updated.text

    deleted = await client.delete(
        f"/api/v1/communication/messages/{message['id']}", headers=headers
    )
    assert deleted.status_code == 200, deleted.text

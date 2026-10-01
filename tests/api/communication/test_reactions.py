"""Message reaction API tests."""

from __future__ import annotations

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
async def test_message_reactions(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    other_user_id, _, _ = await create_peer_user(client, headers)
    conv_id = await _direct_conversation(client, headers, other_user_id)

    created = await client.post(
        f"/api/v1/communication/conversations/{conv_id}/messages",
        headers=headers,
        json={"body": "React to me"},
    )
    assert created.status_code == 201, created.text
    message_id = created.json()["data"]["id"]

    added = await client.put(
        f"/api/v1/communication/messages/{message_id}/reactions/%F0%9F%91%8D",
        headers=headers,
    )
    assert added.status_code == 201, added.text
    assert added.json()["data"]["emoji"] == "👍"

    removed = await client.delete(
        f"/api/v1/communication/messages/{message_id}/reactions/%F0%9F%91%8D",
        headers=headers,
    )
    assert removed.status_code == 200, removed.text

"""Communication search API tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.api.communication.conftest import create_peer_user
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_search_messages_and_people(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    other_user_id, _, _ = await create_peer_user(client, headers)

    conv = await client.post(
        "/api/v1/communication/conversations",
        headers=headers,
        json={"kind": "DIRECT", "other_user_id": other_user_id},
    )
    assert conv.status_code == 201, conv.text
    conv_id = conv.json()["data"]["id"]

    message = await client.post(
        f"/api/v1/communication/conversations/{conv_id}/messages",
        headers=headers,
        json={"body": "UniqueSearchToken123"},
    )
    assert message.status_code == 201, message.text

    global_search = await client.get(
        "/api/v1/communication/search",
        headers=headers,
        params={"q": "UniqueSearchToken123", "type": "messages"},
    )
    assert global_search.status_code == 200, global_search.text
    results = global_search.json()["data"]["results"]
    assert any(item["conversation_id"] == conv_id for item in results)

    scoped_search = await client.get(
        f"/api/v1/communication/conversations/{conv_id}/messages/search",
        headers=headers,
        params={"q": "UniqueSearchToken123"},
    )
    assert scoped_search.status_code == 200, scoped_search.text
    assert len(scoped_search.json()["data"]) >= 1

    people = await client.get(
        "/api/v1/communication/search",
        headers=headers,
        params={"q": "Peer", "type": "people"},
    )
    assert people.status_code == 200, people.text
    assert len(people.json()["data"]["results"]) >= 1

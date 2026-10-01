"""Message delivered marker API tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.api.communication.conftest import create_peer_user
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_mark_delivered(client: AsyncClient, signaling_events) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    other_user_id, other_email, other_password = await create_peer_user(client, headers)
    other_headers = await login_headers(client, tenant_id, other_email, other_password)

    conv = await client.post(
        "/api/v1/communication/conversations",
        headers=headers,
        json={"kind": "DIRECT", "other_user_id": other_user_id},
    )
    assert conv.status_code == 201, conv.text
    conv_id = conv.json()["data"]["id"]

    created = await client.post(
        f"/api/v1/communication/conversations/{conv_id}/messages",
        headers=headers,
        json={"body": "Delivery test"},
    )
    assert created.status_code == 201, created.text
    seq = created.json()["data"]["seq"]

    delivered = await client.post(
        f"/api/v1/communication/conversations/{conv_id}/delivered",
        headers=other_headers,
        json={"up_to_seq": seq},
    )
    assert delivered.status_code == 200, delivered.text
    assert any(e[2].type == "message.delivered" for e in signaling_events)

"""WebSocket communication gateway tests."""

from __future__ import annotations

import pytest

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_websocket_ticket_mint(client) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)

    ticket_resp = await client.post("/api/v1/communication/ws/ticket", headers=headers)
    assert ticket_resp.status_code == 200, ticket_resp.text
    data = ticket_resp.json()["data"]
    assert data["ticket"]
    assert data["expires_in_seconds"] == 60

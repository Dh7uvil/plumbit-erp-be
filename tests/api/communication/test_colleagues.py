"""Colleague directory API tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.api.auth.test_rbac_guards import _create_user_with_permissions
from tests.api.communication.conftest import create_peer_user
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_colleagues_lists_peers_without_user_read(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    peer_id, _, _ = await create_peer_user(client, headers)

    response = await client.get("/api/v1/communication/colleagues", headers=headers)
    assert response.status_code == 200, response.text
    ids = {row["id"] for row in response.json()["data"]}
    assert peer_id in ids


@pytest.mark.asyncio
async def test_colleagues_available_to_communication_only_role(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    peer_id, _, peer_password = await create_peer_user(client, headers)
    _, limited_email, limited_password = await _create_user_with_permissions(
        client,
        headers,
        permission_codes=[
            "communication.conversation.read",
            "communication.conversation.create",
        ],
    )
    limited_headers = await login_headers(client, tenant_id, limited_email, limited_password)

    response = await client.get("/api/v1/communication/colleagues", headers=limited_headers)
    assert response.status_code == 200, response.text
    ids = {row["id"] for row in response.json()["data"]}
    assert peer_id in ids

    users_response = await client.get("/api/v1/users", headers=limited_headers)
    assert users_response.status_code == 403, users_response.text

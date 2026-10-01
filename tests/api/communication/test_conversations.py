"""Conversation API tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.communication.conftest import create_peer_user
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_direct_conversation_idempotent(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    other_user_id, other_email, other_password = await create_peer_user(client, headers)
    _ = other_email, other_password

    first = await client.post(
        "/api/v1/communication/conversations",
        headers=headers,
        json={"kind": "DIRECT", "other_user_id": other_user_id},
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        "/api/v1/communication/conversations",
        headers=headers,
        json={"kind": "DIRECT", "other_user_id": other_user_id},
    )
    assert second.status_code == 201, second.text
    data = first.json()["data"]
    assert data["id"] == second.json()["data"]["id"]
    participant_ids = {p["user_id"] for p in data["participants"]}
    assert len(participant_ids) == 2
    assert other_user_id in participant_ids

    fetched = await client.get(
        f"/api/v1/communication/conversations/{data['id']}",
        headers=headers,
    )
    assert fetched.status_code == 200, fetched.text
    assert len(fetched.json()["data"]["participants"]) == 2


@pytest.mark.asyncio
async def test_direct_conversation_one_per_user_pair(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    first_peer_id, _, _ = await create_peer_user(client, headers)
    second_peer_id, _, _ = await create_peer_user(client, headers)

    first = await client.post(
        "/api/v1/communication/conversations",
        headers=headers,
        json={"kind": "DIRECT", "other_user_id": first_peer_id},
    )
    second = await client.post(
        "/api/v1/communication/conversations",
        headers=headers,
        json={"kind": "DIRECT", "other_user_id": second_peer_id},
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["data"]["id"] != second.json()["data"]["id"]


@pytest.mark.asyncio
async def test_group_conversation_crud(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    created = await client.post(
        "/api/v1/communication/conversations",
        headers=headers,
        json={"kind": "GROUP", "name": "Engineering", "participant_user_ids": []},
    )
    assert created.status_code == 201, created.text
    conv_id = created.json()["data"]["id"]

    listed = await client.get("/api/v1/communication/conversations", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["meta"]["total"] >= 1

    updated = await client.patch(
        f"/api/v1/communication/conversations/{conv_id}",
        headers=headers,
        json={"description": "Team chat"},
    )
    assert updated.status_code == 200, updated.text

    deleted = await client.delete(
        f"/api/v1/communication/conversations/{conv_id}", headers=headers
    )
    assert deleted.status_code == 200, deleted.text

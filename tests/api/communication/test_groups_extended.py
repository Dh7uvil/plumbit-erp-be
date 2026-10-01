"""Extended group API tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.api.communication.conftest import create_peer_user
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_group_membership_lifecycle(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    member_id, _, _ = await create_peer_user(client, headers)

    created = await client.post(
        "/api/v1/communication/groups",
        headers=headers,
        json={
            "name": "Ops",
            "description": "Operations team",
            "member_user_ids": [member_id],
        },
    )
    assert created.status_code == 201, created.text
    group_id = created.json()["data"]["id"]
    participant_ids = {p["user_id"] for p in created.json()["data"]["participants"]}
    assert member_id in participant_ids

    updated = await client.patch(
        f"/api/v1/communication/groups/{group_id}",
        headers=headers,
        json={"description": "Updated operations team"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["description"] == "Updated operations team"

    promoted = await client.post(
        f"/api/v1/communication/groups/{group_id}/admins/{member_id}",
        headers=headers,
    )
    assert promoted.status_code == 201, promoted.text
    roles = {p["user_id"]: p["role"] for p in promoted.json()["data"]["participants"]}
    assert roles[member_id] == "ADMIN"

    demoted = await client.delete(
        f"/api/v1/communication/groups/{group_id}/admins/{member_id}",
        headers=headers,
    )
    assert demoted.status_code == 200, demoted.text
    roles = {p["user_id"]: p["role"] for p in demoted.json()["data"]["participants"]}
    assert roles[member_id] == "MEMBER"

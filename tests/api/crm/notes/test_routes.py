"""API tests for note CRUD."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_note_crud(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    lead = await client.post(
        "/api/v1/leads",
        headers=headers,
        json={"company_name": f"Notes {uuid4().hex[:8]}"},
    )
    assert lead.status_code == 201, lead.text
    lead_id = lead.json()["data"]["id"]
    created = await client.post(
        "/api/v1/notes",
        headers=headers,
        json={
            "body": "First conversation",
            "related_entity_type": "lead",
            "related_entity_id": lead_id,
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    assert row["body"] == "First conversation"

    listed = await client.get(
        "/api/v1/notes",
        headers=headers,
        params={"related_entity_type": "lead", "related_entity_id": lead_id},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["meta"]["total"] == 1

    updated = await client.patch(
        f"/api/v1/notes/{row['id']}",
        headers=headers,
        json={"body": "Updated note"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["body"] == "Updated note"

    deleted = await client.delete(f"/api/v1/notes/{row['id']}", headers=headers)
    assert deleted.status_code == 200, deleted.text

"""API tests for lead CRUD and workflow."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_lead_crud_assign_and_status(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:6]
    created = await client.post(
        "/api/v1/leads",
        headers=headers,
        json={
            "first_name": "Alex",
            "last_name": f"River {suffix}",
            "company_name": "Acme Trading",
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    assert row["lead_number"].startswith("LEAD-")
    assert row["status"] == "NEW"
    assert row["version"] == 1

    qualified = await client.post(
        f"/api/v1/leads/{row['id']}/status",
        headers={**headers, "If-Match": str(row["version"])},
        json={"status": "QUALIFIED"},
    )
    assert qualified.status_code == 200, qualified.text
    assert qualified.json()["data"]["status"] == "QUALIFIED"
    assert qualified.json()["data"]["version"] == 2

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    owner_id = me.json()["data"]["id"]
    assigned = await client.post(
        f"/api/v1/leads/{row['id']}/assign",
        headers={**headers, "If-Match": "2"},
        json={"owner_id": owner_id},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["data"]["owner_id"] == owner_id

    stale = await client.patch(
        f"/api/v1/leads/{row['id']}",
        headers={**headers, "If-Match": "1"},
        json={"notes": "Should fail"},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "DOCUMENT_STALE"

    deleted = await client.delete(f"/api/v1/leads/{row['id']}", headers=headers)
    assert deleted.status_code == 200, deleted.text


@pytest.mark.asyncio
async def test_invalid_status_transition(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    created = await client.post(
        "/api/v1/leads",
        headers=headers,
        json={"company_name": f"Blocked {uuid4().hex[:8]}"},
    )
    assert created.status_code == 201, created.text
    lead_id = created.json()["data"]["id"]
    response = await client.post(
        f"/api/v1/leads/{lead_id}/status",
        headers={**headers, "If-Match": "1"},
        json={"status": "CONVERTED"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"

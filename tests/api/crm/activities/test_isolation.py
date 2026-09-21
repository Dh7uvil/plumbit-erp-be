"""Tenant isolation for activities."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_activity_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    lead = await client.post(
        "/api/v1/leads",
        headers=headers_a,
        json={"company_name": f"Iso {uuid4().hex[:8]}"},
    )
    assert lead.status_code == 201, lead.text
    created = await client.post(
        "/api/v1/activities",
        headers=headers_a,
        json={
            "activity_type": "MEETING",
            "subject": "Kickoff",
            "related_entity_type": "lead",
            "related_entity_id": lead.json()["data"]["id"],
        },
    )
    assert created.status_code == 201, created.text
    activity_id = created.json()["data"]["id"]
    fetched = await client.get(f"/api/v1/activities/{activity_id}", headers=headers_b)
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

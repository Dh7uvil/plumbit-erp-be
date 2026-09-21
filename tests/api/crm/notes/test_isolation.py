"""Tenant isolation for notes."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_note_tenant_isolation(client: AsyncClient) -> None:
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
        "/api/v1/notes",
        headers=headers_a,
        json={
            "body": "Private note",
            "related_entity_type": "lead",
            "related_entity_id": lead.json()["data"]["id"],
        },
    )
    assert created.status_code == 201, created.text
    note_id = created.json()["data"]["id"]
    fetched = await client.get(f"/api/v1/notes/{note_id}", headers=headers_b)
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

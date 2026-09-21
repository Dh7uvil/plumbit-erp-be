"""Tenant isolation for campaigns."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_campaign_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    created = await client.post(
        "/api/v1/campaigns",
        headers=headers_a,
        json={"name": f"Iso {uuid4().hex[:8]}", "campaign_type": "OTHER"},
    )
    assert created.status_code == 201, created.text
    campaign_id = created.json()["data"]["id"]
    fetched = await client.get(f"/api/v1/campaigns/{campaign_id}", headers=headers_b)
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    roi = await client.get(f"/api/v1/campaigns/{campaign_id}/roi", headers=headers_b)
    assert roi.status_code == 404
    assert roi.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

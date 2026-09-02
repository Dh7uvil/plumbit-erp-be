"""Tenant isolation for units of measure."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_unit_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    suffix = uuid4().hex[:8]
    created = await client.post(
        "/api/v1/units",
        headers=headers_a,
        json={"code": f"U{suffix[:6]}", "name": f"Unit {suffix}"},
    )
    assert created.status_code == 201, created.text
    unit_id = created.json()["data"]["id"]
    fetched = await client.get(f"/api/v1/units/{unit_id}", headers=headers_b)
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    listed = await client.get("/api/v1/units", headers=headers_b)
    assert listed.status_code == 200
    assert all(item["id"] != unit_id for item in listed.json()["data"])

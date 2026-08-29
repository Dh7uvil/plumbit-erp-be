"""Tenant isolation for products."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_product_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    suffix = uuid4().hex[:8]
    created = await client.post(
        "/api/v1/products",
        headers=headers_a,
        json={"sku": f"SKU-{suffix}", "name": f"Item {suffix}", "selling_rate": "10.0000"},
    )
    assert created.status_code == 201, created.text
    product_id = created.json()["data"]["id"]
    fetched = await client.get(f"/api/v1/products/{product_id}", headers=headers_b)
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    listed = await client.get("/api/v1/products", headers=headers_b)
    assert listed.status_code == 200
    assert all(item["id"] != product_id for item in listed.json()["data"])

"""Tenant isolation for customers."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_customer_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    suffix = uuid4().hex[:8]
    currency = await client.post(
        "/api/v1/currencies",
        headers=headers_a,
        json={
            "code": "AED",
            "name": "UAE Dirham",
            "symbol": "AED",
            "is_base": True,
        },
    )
    assert currency.status_code == 201, currency.text
    created = await client.post(
        "/api/v1/customers",
        headers=headers_a,
        json={
            "name": f"Acme {suffix}",
            "code": f"C-{suffix}",
            "tax_treatment": "UNREGISTERED",
            "currency_id": currency.json()["data"]["id"],
        },
    )
    assert created.status_code == 201, created.text
    customer_id = created.json()["data"]["id"]
    fetched = await client.get(f"/api/v1/customers/{customer_id}", headers=headers_b)
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    listed = await client.get("/api/v1/customers", headers=headers_b)
    assert listed.status_code == 200
    assert all(item["id"] != customer_id for item in listed.json()["data"])

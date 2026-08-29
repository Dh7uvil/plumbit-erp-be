"""Tenant isolation and primary-contact rules."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _create_customer(client: AsyncClient, headers: dict[str, str], suffix: str) -> str:
    currencies = await client.get("/api/v1/currencies?is_base=true", headers=headers)
    assert currencies.status_code == 200, currencies.text
    currency_id = currencies.json()["data"][0]["id"]
    created = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "name": f"Acme {suffix}",
            "code": f"C-{suffix}",
            "tax_treatment": "UNREGISTERED",
            "currency_id": currency_id,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


@pytest.mark.asyncio
async def test_contact_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    suffix = uuid4().hex[:8]
    customer_id = await _create_customer(client, headers_a, suffix)
    created = await client.post(
        "/api/v1/contacts",
        headers=headers_a,
        json={"customer_id": customer_id, "name": f"Pat {suffix}", "is_primary": True},
    )
    assert created.status_code == 201, created.text
    contact_id = created.json()["data"]["id"]
    fetched = await client.get(f"/api/v1/contacts/{contact_id}", headers=headers_b)
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    listed = await client.get("/api/v1/contacts", headers=headers_b)
    assert listed.status_code == 200
    assert all(item["id"] != contact_id for item in listed.json()["data"])


@pytest.mark.asyncio
async def test_contact_second_primary_unsets_first(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:8]
    customer_id = await _create_customer(client, headers, suffix)
    first = await client.post(
        "/api/v1/contacts",
        headers=headers,
        json={"customer_id": customer_id, "name": f"First {suffix}", "is_primary": True},
    )
    assert first.status_code == 201, first.text
    first_row = first.json()["data"]
    assert first_row["is_primary"] is True
    second = await client.post(
        "/api/v1/contacts",
        headers=headers,
        json={"customer_id": customer_id, "name": f"Second {suffix}", "is_primary": True},
    )
    assert second.status_code == 201, second.text
    assert second.json()["data"]["is_primary"] is True
    fetched_first = await client.get(f"/api/v1/contacts/{first_row['id']}", headers=headers)
    assert fetched_first.status_code == 200, fetched_first.text
    assert fetched_first.json()["data"]["is_primary"] is False


@pytest.mark.asyncio
async def test_contact_unknown_customer_not_found(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    created = await client.post(
        "/api/v1/contacts",
        headers=headers,
        json={"customer_id": str(uuid4()), "name": "Orphan"},
    )
    assert created.status_code == 404, created.text
    assert created.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

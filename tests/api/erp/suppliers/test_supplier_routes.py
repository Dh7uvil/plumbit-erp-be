"""Supplier/customer partition, BOTH, delete, contacts, and permissions."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _currency_id(client: AsyncClient, headers: dict[str, str]) -> str:
    currencies = await client.get("/api/v1/currencies?is_base=true", headers=headers)
    assert currencies.status_code == 200, currencies.text
    return str(currencies.json()["data"][0]["id"])


async def _create_party(
    client: AsyncClient,
    headers: dict[str, str],
    path: str,
    *,
    name: str,
    code: str,
    currency_id: str,
    company_type: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "code": code,
        "tax_treatment": "UNREGISTERED",
        "currency_id": currency_id,
    }
    if company_type is not None:
        payload["company_type"] = company_type
    created = await client.post(f"/api/v1{path}", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    return created.json()["data"]


@pytest.mark.asyncio
async def test_supplier_create_is_hidden_from_customers(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:8]
    currency_id = await _currency_id(client, headers)
    supplier = await _create_party(
        client,
        headers,
        "/suppliers",
        name=f"Vendor {suffix}",
        code=f"S-{suffix}",
        currency_id=currency_id,
    )
    assert supplier["company_type"] == "SUPPLIER"
    supplier_id = supplier["id"]
    listed_suppliers = await client.get("/api/v1/suppliers", headers=headers)
    assert listed_suppliers.status_code == 200
    assert any(item["id"] == supplier_id for item in listed_suppliers.json()["data"])
    listed_customers = await client.get("/api/v1/customers", headers=headers)
    assert listed_customers.status_code == 200
    assert all(item["id"] != supplier_id for item in listed_customers.json()["data"])
    fetched = await client.get(f"/api/v1/customers/{supplier_id}", headers=headers)
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_customer_create_is_hidden_from_suppliers(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:8]
    currency_id = await _currency_id(client, headers)
    customer = await _create_party(
        client,
        headers,
        "/customers",
        name=f"Acme {suffix}",
        code=f"C-{suffix}",
        currency_id=currency_id,
    )
    assert customer["company_type"] == "CUSTOMER"
    customer_id = customer["id"]
    listed_suppliers = await client.get("/api/v1/suppliers", headers=headers)
    assert listed_suppliers.status_code == 200
    assert all(item["id"] != customer_id for item in listed_suppliers.json()["data"])
    fetched = await client.get(f"/api/v1/suppliers/{customer_id}", headers=headers)
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_both_visible_and_patchable_on_each_api(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:8]
    currency_id = await _currency_id(client, headers)
    party = await _create_party(
        client,
        headers,
        "/customers",
        name=f"Both {suffix}",
        code=f"B-{suffix}",
        currency_id=currency_id,
        company_type="BOTH",
    )
    party_id = party["id"]
    as_customer = await client.get(f"/api/v1/customers/{party_id}", headers=headers)
    as_supplier = await client.get(f"/api/v1/suppliers/{party_id}", headers=headers)
    assert as_customer.status_code == 200, as_customer.text
    assert as_supplier.status_code == 200, as_supplier.text
    assert as_customer.json()["data"]["id"] == as_supplier.json()["data"]["id"] == party_id
    patched = await client.patch(
        f"/api/v1/suppliers/{party_id}",
        headers=headers,
        json={"name": f"Both renamed {suffix}"},
    )
    assert patched.status_code == 200, patched.text
    fetched = await client.get(f"/api/v1/customers/{party_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["data"]["name"] == f"Both renamed {suffix}"
    promoted = await client.patch(
        f"/api/v1/customers/{party_id}",
        headers=headers,
        json={"company_type": "BOTH"},
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["data"]["company_type"] == "BOTH"


@pytest.mark.asyncio
async def test_promote_supplier_to_both_appears_on_customers(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:8]
    currency_id = await _currency_id(client, headers)
    supplier = await _create_party(
        client,
        headers,
        "/suppliers",
        name=f"Vendor {suffix}",
        code=f"S-{suffix}",
        currency_id=currency_id,
    )
    supplier_id = supplier["id"]
    hidden = await client.get(f"/api/v1/customers/{supplier_id}", headers=headers)
    assert hidden.status_code == 404
    promoted = await client.patch(
        f"/api/v1/suppliers/{supplier_id}",
        headers=headers,
        json={"company_type": "BOTH"},
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["data"]["company_type"] == "BOTH"
    fetched = await client.get(f"/api/v1/customers/{supplier_id}", headers=headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["data"]["id"] == supplier_id


@pytest.mark.asyncio
async def test_delete_both_from_suppliers_hides_from_customers(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:8]
    currency_id = await _currency_id(client, headers)
    party = await _create_party(
        client,
        headers,
        "/suppliers",
        name=f"Shared {suffix}",
        code=f"SH-{suffix}",
        currency_id=currency_id,
        company_type="BOTH",
    )
    party_id = party["id"]
    deleted = await client.delete(f"/api/v1/suppliers/{party_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    fetched = await client.get(f"/api/v1/customers/{party_id}", headers=headers)
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_contact_create_on_supplier_party(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:8]
    currency_id = await _currency_id(client, headers)
    supplier = await _create_party(
        client,
        headers,
        "/suppliers",
        name=f"Vendor {suffix}",
        code=f"S-{suffix}",
        currency_id=currency_id,
    )
    created = await client.post(
        "/api/v1/contacts",
        headers=headers,
        json={"customer_id": supplier["id"], "name": f"Pat {suffix}"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["customer_id"] == supplier["id"]


@pytest.mark.asyncio
async def test_supplier_read_requires_permission(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    permissions = await client.get("/api/v1/permissions?page_size=200", headers=headers)
    assert permissions.status_code == 200, permissions.text
    codes = {item["code"]: item["id"] for item in permissions.json()["data"]}
    suffix = uuid4().hex[:8]
    role = await client.post(
        "/api/v1/roles",
        headers=headers,
        json={
            "name": f"Limited {suffix}",
            "permission_ids": [codes["identity.user.read"], codes["crm.customer.read"]],
        },
    )
    assert role.status_code == 201, role.text
    limited_email = f"limited-{suffix}@example.com"
    user = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "Limited User",
            "email": limited_email,
            "password": "password12",
            "role_ids": [role.json()["data"]["id"]],
        },
    )
    assert user.status_code == 201, user.text
    limited_headers = await login_headers(client, tenant_id, limited_email, "password12")
    denied = await client.get("/api/v1/suppliers", headers=limited_headers)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "PERMISSION_DENIED"
    allowed = await client.get("/api/v1/customers", headers=limited_headers)
    assert allowed.status_code == 200, allowed.text


@pytest.mark.asyncio
async def test_customer_api_rejects_supplier_company_type(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:8]
    currency_id = await _currency_id(client, headers)
    created = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "name": f"Bad {suffix}",
            "code": f"X-{suffix}",
            "tax_treatment": "UNREGISTERED",
            "currency_id": currency_id,
            "company_type": "SUPPLIER",
        },
    )
    assert created.status_code == 422, created.text
    assert created.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_supplier_api_rejects_customer_company_type(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:8]
    currency_id = await _currency_id(client, headers)
    created = await client.post(
        "/api/v1/suppliers",
        headers=headers,
        json={
            "name": f"Bad {suffix}",
            "code": f"X-{suffix}",
            "tax_treatment": "UNREGISTERED",
            "currency_id": currency_id,
            "company_type": "CUSTOMER",
        },
    )
    assert created.status_code == 422, created.text
    assert created.json()["error"]["code"] == "VALIDATION_ERROR"

"""Characterization tests for existing compose-defaults endpoints (regression guard)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import ADMIN_PASSWORD, login_headers, provision_admin
from tests.api.erp.sales_orders.test_routes import _create_customer, _seeded_ids


async def _create_supplier(client: AsyncClient, headers: dict[str, str]) -> str:
    suffix = uuid4().hex[:8]
    payload: dict[str, object] = {
        "name": f"Supplier {suffix}",
        "tax_treatment": "REGISTERED",
        "trn": f"{int(uuid4().int % (10**15 - 1)) + 1:015d}",
        "billing_address": {
            "address_line_1": "Warehouse 1",
            "city": "Dubai",
            "state": "DUBAI",
            "country_code": "AE",
            "country": "United Arab Emirates",
        },
    }
    response = await client.post("/api/v1/suppliers", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def _assert_customer_compose_shape(data: dict[str, object], *, customer_id: str) -> None:
    assert data["customer_id"] == customer_id
    assert isinstance(data["customer_name"], str) and data["customer_name"]
    assert data["tax_treatment"] in {
        "REGISTERED",
        "UNREGISTERED",
        "EXPORT",
        "GCC",
        "DESIGNATED_ZONE",
    }
    assert isinstance(data["currency_id"], str)
    assert "place_of_supply" in data
    assert "bill_to_snapshot" in data
    assert "ship_to_snapshot" in data


@pytest.mark.asyncio
async def test_sales_order_compose_defaults_matches_customer(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    response = await client.get(
        "/api/v1/sales-orders/compose-defaults",
        headers=headers,
        params={"customer_id": customer_id},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    _assert_customer_compose_shape(data, customer_id=customer_id)
    assert "price_list_id" in data
    assert "salesperson_id" in data
    assert "terms_and_conditions" in data


@pytest.mark.asyncio
async def test_quotation_compose_defaults_matches_customer(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    response = await client.get(
        "/api/v1/quotations/compose-defaults",
        headers=headers,
        params={"customer_id": customer_id},
    )
    assert response.status_code == 200, response.text
    _assert_customer_compose_shape(data := response.json()["data"], customer_id=customer_id)
    assert "price_list_id" in data


@pytest.mark.asyncio
async def test_proforma_compose_defaults_matches_customer(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    response = await client.get(
        "/api/v1/proforma-invoices/compose-defaults",
        headers=headers,
        params={"customer_id": customer_id},
    )
    assert response.status_code == 200, response.text
    _assert_customer_compose_shape(data := response.json()["data"], customer_id=customer_id)


@pytest.mark.asyncio
async def test_purchase_order_compose_defaults_matches_supplier(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _seeded_ids(client, headers)
    supplier_id = await _create_supplier(client, headers)
    response = await client.get(
        "/api/v1/purchase-orders/compose-defaults",
        headers=headers,
        params={"supplier_id": supplier_id},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["supplier_id"] == supplier_id
    assert isinstance(data["supplier_name"], str)
    assert isinstance(data["currency_id"], str)
    assert "supplier_address_snapshot" in data
    assert "deliver_to_snapshot" in data


@pytest.mark.asyncio
async def test_compose_defaults_other_tenant_returns_404(client: AsyncClient) -> None:
    tenant_a, email_a, _ = await provision_admin(name="Tenant A")
    tenant_b, email_b, _ = await provision_admin(name="Tenant B")
    headers_a = await login_headers(client, tenant_a, email_a, ADMIN_PASSWORD)
    headers_b = await login_headers(client, tenant_b, email_b, ADMIN_PASSWORD)
    await _seeded_ids(client, headers_a)
    customer_id = await _create_customer(client, headers_a)
    response = await client.get(
        "/api/v1/sales-orders/compose-defaults",
        headers=headers_b,
        params={"customer_id": customer_id},
    )
    assert response.status_code == 404

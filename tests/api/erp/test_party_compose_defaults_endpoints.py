"""Tests for new party compose-defaults endpoints."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin
from tests.api.erp.sales_orders.test_routes import _create_customer, _seeded_ids


async def _create_supplier(client: AsyncClient, headers: dict[str, str]) -> str:
    suffix = uuid4().hex[:8]
    response = await client.post(
        "/api/v1/suppliers",
        headers=headers,
        json={
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
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


@pytest.mark.parametrize(
    "path,param_name,party_factory",
    [
        ("/api/v1/sales-invoices/compose-defaults", "customer_id", "customer"),
        ("/api/v1/credit-notes/compose-defaults", "customer_id", "customer"),
        ("/api/v1/delivery-notes/compose-defaults", "customer_id", "customer"),
        ("/api/v1/sales-returns/compose-defaults", "customer_id", "customer"),
        ("/api/v1/purchase-invoices/compose-defaults", "supplier_id", "supplier"),
        ("/api/v1/debit-notes/compose-defaults", "supplier_id", "supplier"),
        ("/api/v1/goods-receipts/compose-defaults", "supplier_id", "supplier"),
        ("/api/v1/purchase-returns/compose-defaults", "supplier_id", "supplier"),
    ],
)
@pytest.mark.asyncio
async def test_compose_defaults_endpoints_ok(
    client: AsyncClient, path: str, param_name: str, party_factory: str
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _seeded_ids(client, headers)
    party_id = (
        await _create_customer(client, headers)
        if party_factory == "customer"
        else await _create_supplier(client, headers)
    )
    response = await client.get(path, headers=headers, params={param_name: party_id})
    assert response.status_code == 200, response.text
    assert response.json()["data"][param_name] == party_id


@pytest.mark.asyncio
async def test_customer_payment_compose_defaults(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    response = await client.get(
        "/api/v1/customer-payments/compose-defaults",
        headers=headers,
        params={"customer_id": customer_id},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["customer_id"] == customer_id
    assert "currency_id" in data


@pytest.mark.asyncio
async def test_product_line_defaults(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    from tests.api.erp.sales_orders.test_routes import _create_product

    product_id = await _create_product(client, headers, ids)
    response = await client.get(
        f"/api/v1/products/{product_id}/line-defaults",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["unit_id"] == ids["pcs"]
    assert data["rate"] is not None

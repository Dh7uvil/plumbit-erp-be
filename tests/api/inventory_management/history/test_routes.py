"""API tests for trading history projections."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.api.inventory_management.delivery_notes.test_routes import (
    _confirm_sales_order,
    _create_and_post_delivery_note,
    _receive_stock,
)
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_product_and_customer_sales_history_use_posted_notes(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _receive_stock(client, headers, quantity="4")
    product_id = str(ctx["product_id"])
    order = await _confirm_sales_order(client, headers, product_id=product_id, quantity="4")
    await _create_and_post_delivery_note(client, headers, order["id"])

    customers = await client.get(f"/api/v1/products/{product_id}/customers", headers=headers)
    assert customers.status_code == 200, customers.text
    assert len(customers.json()["data"]) == 1
    assert Decimal(customers.json()["data"][0]["total_quantity"]) == Decimal("4")

    sales = await client.get(f"/api/v1/products/{product_id}/sales-history", headers=headers)
    assert sales.status_code == 200, sales.text
    assert Decimal(sales.json()["data"][0]["quantity"]) == Decimal("4")
    assert sales.json()["data"][0]["unit_cost"] is not None

    customer_id = order["customer_id"]
    products = await client.get(f"/api/v1/customers/{customer_id}/products", headers=headers)
    assert products.status_code == 200, products.text
    assert products.json()["data"][0]["product_id"] == product_id

    purchases = await client.get(f"/api/v1/products/{product_id}/purchase-history", headers=headers)
    assert purchases.status_code == 200, purchases.text
    assert Decimal(purchases.json()["data"][0]["quantity"]) == Decimal("4")

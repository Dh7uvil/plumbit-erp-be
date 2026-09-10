"""API tests for trading history projections."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.inventory_management.delivery_notes.test_routes import (
    _confirm_sales_order,
    _create_and_post_delivery_note,
    _idempotent,
    _receive_stock,
)
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_product_and_customer_sales_history_use_posted_notes(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    today = datetime.now(UTC).date().isoformat()
    updated = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"books_start_date": today},
    )
    assert updated.status_code == 200, updated.text
    ctx = await _receive_stock(client, headers, quantity="4")
    product_id = str(ctx["product_id"])
    order = await _confirm_sales_order(client, headers, product_id=product_id, quantity="4")
    note = await _create_and_post_delivery_note(client, headers, order["id"])

    customers = await client.get(f"/api/v1/products/{product_id}/customers", headers=headers)
    assert customers.status_code == 200, customers.text
    assert len(customers.json()["data"]) == 1
    assert Decimal(customers.json()["data"][0]["total_quantity"]) == Decimal("4")
    assert Decimal(customers.json()["data"][0]["invoiced_quantity"]) == Decimal("0")

    sales = await client.get(f"/api/v1/products/{product_id}/sales-history", headers=headers)
    assert sales.status_code == 200, sales.text
    assert Decimal(sales.json()["data"][0]["quantity"]) == Decimal("4")
    assert sales.json()["data"][0]["unit_cost"] is not None
    assert Decimal(sales.json()["data"][0]["invoiced_quantity"]) == Decimal("0")

    created = await client.post(
        "/api/v1/sales-invoices/from-delivery-notes",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"delivery_note_ids": [note["id"]]},
    )
    assert created.status_code == 201, created.text
    posted = await client.post(
        f"/api/v1/sales-invoices/{created.json()['data']['id']}/post",
        headers=_idempotent(headers, created.json()["data"]["version"]),
    )
    assert posted.status_code == 200, posted.text
    invoice = posted.json()["data"]
    invoiced_qty = Decimal(invoice["lines"][0]["quantity"])
    revenue = Decimal(invoice["lines"][0]["amount"])

    customers = await client.get(f"/api/v1/products/{product_id}/customers", headers=headers)
    assert Decimal(customers.json()["data"][0]["invoiced_quantity"]) == invoiced_qty
    assert Decimal(customers.json()["data"][0]["revenue"]) == revenue

    sales = await client.get(f"/api/v1/products/{product_id}/sales-history", headers=headers)
    assert Decimal(sales.json()["data"][0]["invoiced_quantity"]) == invoiced_qty
    assert Decimal(sales.json()["data"][0]["revenue"]) == revenue

    customer_id = order["customer_id"]
    products = await client.get(f"/api/v1/customers/{customer_id}/products", headers=headers)
    assert products.status_code == 200, products.text
    assert products.json()["data"][0]["product_id"] == product_id
    assert Decimal(products.json()["data"][0]["invoiced_quantity"]) == invoiced_qty
    assert Decimal(products.json()["data"][0]["revenue"]) == revenue

    customer_sales = await client.get(
        f"/api/v1/customers/{customer_id}/sales-history", headers=headers
    )
    assert customer_sales.status_code == 200, customer_sales.text
    assert Decimal(customer_sales.json()["data"][0]["invoiced_quantity"]) == invoiced_qty
    assert Decimal(customer_sales.json()["data"][0]["revenue"]) == revenue

    purchases = await client.get(f"/api/v1/products/{product_id}/purchase-history", headers=headers)
    assert purchases.status_code == 200, purchases.text
    assert Decimal(purchases.json()["data"][0]["quantity"]) == Decimal("4")
    assert Decimal(purchases.json()["data"][0]["billed_cost"]) == Decimal("0")

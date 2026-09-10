"""API tests for sales returns: partial restore at original cost."""

from __future__ import annotations

from decimal import Decimal

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
async def test_partial_restock_return_restores_original_cost(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _receive_stock(client, headers, quantity="6")
    product_id = str(ctx["product_id"])
    order = await _confirm_sales_order(client, headers, product_id=product_id, quantity="6")
    note = await _create_and_post_delivery_note(client, headers, order["id"])
    dn_line = note["lines"][0]

    created = await client.post(
        "/api/v1/sales-returns",
        headers=headers,
        json={
            "delivery_note_id": note["id"],
            "reason_code": "WRONG_ITEM_SHIPPED",
            "lines": [
                {
                    "delivery_note_line_id": dn_line["id"],
                    "product_id": dn_line["product_id"],
                    "quantity": "2",
                    "disposition": "RESTOCK",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    posted = await client.post(
        f"/api/v1/sales-returns/{created.json()['data']['id']}/post",
        headers=_idempotent(headers, created.json()["data"]["version"]),
    )
    assert posted.status_code == 200, posted.text
    assert posted.json()["data"]["status"] == "POSTED"

    stock = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    row = stock.json()["data"][0]
    assert Decimal(row["qty_on_hand"]) == Decimal("2")
    assert Decimal(row["qty_available"]) == Decimal("2")
    layers = await client.get(f"/api/v1/stock/{row['id']}/layers", headers=headers)
    assert Decimal(layers.json()["data"][0]["unit_cost"]) == Decimal("80.0000")

    so = await client.get(f"/api/v1/sales-orders/{order['id']}", headers=headers)
    assert so.json()["data"]["fulfillment_status"] == "PARTIALLY_DELIVERED"
    assert Decimal(so.json()["data"]["lines"][0]["qty_returned"]) == Decimal("2")
    assert Decimal(so.json()["data"]["lines"][0]["qty_reserved"]) == Decimal("0")

    overflow = await client.post(
        "/api/v1/sales-returns",
        headers=headers,
        json={
            "delivery_note_id": note["id"],
            "reason_code": "WRONG_ITEM_SHIPPED",
            "lines": [
                {
                    "delivery_note_line_id": dn_line["id"],
                    "quantity": "5",
                    "disposition": "RESTOCK",
                }
            ],
        },
    )
    assert overflow.status_code == 422, overflow.text


@pytest.mark.asyncio
async def test_cancel_posted_return_restores_pre_return_stock(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _receive_stock(client, headers, quantity="6")
    product_id = str(ctx["product_id"])
    order = await _confirm_sales_order(client, headers, product_id=product_id, quantity="6")
    note = await _create_and_post_delivery_note(client, headers, order["id"])
    dn_line = note["lines"][0]

    created = await client.post(
        "/api/v1/sales-returns",
        headers=headers,
        json={
            "delivery_note_id": note["id"],
            "reason_code": "WRONG_ITEM_SHIPPED",
            "lines": [
                {
                    "delivery_note_line_id": dn_line["id"],
                    "product_id": dn_line["product_id"],
                    "quantity": "2",
                    "disposition": "RESTOCK",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    posted = await client.post(
        f"/api/v1/sales-returns/{created.json()['data']['id']}/post",
        headers=_idempotent(headers, created.json()["data"]["version"]),
    )
    assert posted.status_code == 200, posted.text
    body = posted.json()["data"]

    cancelled = await client.post(
        f"/api/v1/sales-returns/{body['id']}/cancel",
        headers=_idempotent(headers, body["version"]),
        json={"reason": "Posted in error"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["status"] == "CANCELLED"
    assert cancelled.json()["data"]["is_posted"] is False

    stock = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    row = stock.json()["data"][0]
    assert Decimal(row["qty_on_hand"]) == Decimal("0")
    so = await client.get(f"/api/v1/sales-orders/{order['id']}", headers=headers)
    assert Decimal(so.json()["data"]["lines"][0]["qty_returned"]) == Decimal("0")

"""API tests for delivery notes: reservation release, post, and cancel."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.purchase_orders.test_routes import (
    _create_order as _create_purchase_order,
)
from tests.api.erp.purchase_orders.test_routes import (
    _create_product as _create_tracked_product,
)
from tests.api.erp.purchase_orders.test_routes import (
    _create_supplier,
    _seeded_ids,
)
from tests.api.erp.sales_orders.test_routes import (
    _create_customer,
    _if_match,
)
from tests.api.erp.sales_orders.test_routes import (
    _create_order as _create_sales_order,
)
from tests.api.inventory_management.goods_receipts.test_routes import (
    _create_from_po,
    _main_warehouse,
    _post_grn,
)
from tests.conftest import login_headers, provision_admin


def _idempotent(
    headers: dict[str, str], version: object, *, key: str | None = None
) -> dict[str, str]:
    return {**headers, "If-Match": str(version), "Idempotency-Key": key or uuid4().hex}


async def _receive_stock(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    quantity: str = "10",
) -> dict[str, object]:
    ids = await _seeded_ids(client, headers)
    supplier_id = await _create_supplier(client, headers)
    product_id = await _create_tracked_product(client, headers, ids, track_inventory=True)
    created = await _create_purchase_order(
        client, headers, supplier_id=supplier_id, product_id=product_id, quantity=quantity
    )
    issued = await client.post(
        f"/api/v1/purchase-orders/{created['body']['data']['id']}/issue",
        headers=_if_match(headers, created["body"]["data"]["version"]),
    )
    assert issued.status_code == 200, issued.text
    receipt = await _create_from_po(client, headers, issued.json()["data"]["id"])
    assert receipt["status_code"] == 201, receipt["text"]
    posted = await _post_grn(
        client, headers, receipt["body"]["data"]["id"], receipt["body"]["data"]["version"]
    )
    assert posted.status_code == 200, posted.text
    return {
        "product_id": product_id,
        "warehouse_id": await _main_warehouse(client, headers),
        "ids": ids,
    }


async def _confirm_sales_order(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    product_id: str,
    quantity: str = "10",
) -> dict[str, object]:
    customer_id = await _create_customer(client, headers)
    created = await _create_sales_order(
        client, headers, customer_id=customer_id, product_id=product_id, quantity=quantity
    )
    assert created["status_code"] == 201, created["text"]
    confirmed = await client.post(
        f"/api/v1/sales-orders/{created['body']['data']['id']}/confirm",
        headers=_if_match(headers, created["body"]["data"]["version"]),
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()["data"]


async def _create_and_post_delivery_note(
    client: AsyncClient, headers: dict[str, str], sales_order_id: str
) -> dict[str, object]:
    created = await client.post(
        "/api/v1/delivery-notes/from-sales-order",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"sales_order_id": sales_order_id},
    )
    assert created.status_code == 201, created.text
    note = created.json()["data"]
    posted = await client.post(
        f"/api/v1/delivery-notes/{note['id']}/post",
        headers=_idempotent(headers, note["version"]),
    )
    assert posted.status_code == 200, posted.text
    return posted.json()["data"]


@pytest.mark.asyncio
async def test_confirm_with_zero_stock_succeeds_and_reports_shortfall(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    product_id = await _create_tracked_product(client, headers, ids, track_inventory=True)
    order = await _confirm_sales_order(client, headers, product_id=product_id, quantity="4")
    shortfalls = order["reservation_shortfalls"]
    assert len(shortfalls) == 1
    assert Decimal(shortfalls[0]["requested"]) == Decimal("4")
    assert Decimal(shortfalls[0]["reserved"]) == Decimal("0")
    assert Decimal(shortfalls[0]["shortfall"]) == Decimal("4")
    assert Decimal(order["lines"][0]["qty_reserved"]) == Decimal("0")
    stock = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    assert stock.status_code == 200, stock.text
    rows = stock.json()["data"]
    if rows:
        assert Decimal(rows[0]["qty_reserved"]) == Decimal("0")


@pytest.mark.asyncio
async def test_reserved_order_posts_delivery_note_without_insufficient_stock(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _receive_stock(client, headers, quantity="10")
    product_id = str(ctx["product_id"])
    order = await _confirm_sales_order(client, headers, product_id=product_id, quantity="10")
    assert order["reservation_shortfalls"] == []
    assert Decimal(order["lines"][0]["qty_reserved"]) == Decimal("10")

    reserved = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    row = reserved.json()["data"][0]
    assert Decimal(row["qty_on_hand"]) == Decimal("10")
    assert Decimal(row["qty_reserved"]) == Decimal("10")
    assert Decimal(row["qty_available"]) == Decimal("0")

    note = await _create_and_post_delivery_note(client, headers, order["id"])
    assert note["status"] == "POSTED"
    assert Decimal(note["lines"][0]["quantity"]) == Decimal("10")

    stock = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    done = stock.json()["data"][0]
    assert Decimal(done["qty_on_hand"]) == Decimal("0")
    assert Decimal(done["qty_reserved"]) == Decimal("0")
    assert Decimal(done["qty_available"]) == Decimal("0")

    so = await client.get(f"/api/v1/sales-orders/{order['id']}", headers=headers)
    assert so.json()["data"]["fulfillment_status"] == "DELIVERED"
    assert Decimal(so.json()["data"]["lines"][0]["qty_delivered"]) == Decimal("10")
    assert Decimal(so.json()["data"]["lines"][0]["qty_reserved"]) == Decimal("0")


@pytest.mark.asyncio
async def test_cancel_posted_delivery_note_restores_stock_and_reservation(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _receive_stock(client, headers, quantity="5")
    product_id = str(ctx["product_id"])
    order = await _confirm_sales_order(client, headers, product_id=product_id, quantity="5")
    note = await _create_and_post_delivery_note(client, headers, order["id"])
    cancelled = await client.post(
        f"/api/v1/delivery-notes/{note['id']}/cancel",
        headers=_idempotent(headers, note["version"]),
        json={"reason": "Wrong dispatch"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["status"] == "CANCELLED"

    stock = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    row = stock.json()["data"][0]
    assert Decimal(row["qty_on_hand"]) == Decimal("5")
    assert Decimal(row["qty_reserved"]) == Decimal("5")

    so = await client.get(f"/api/v1/sales-orders/{order['id']}", headers=headers)
    assert so.json()["data"]["fulfillment_status"] == "NOT_DELIVERED"
    assert Decimal(so.json()["data"]["lines"][0]["qty_delivered"]) == Decimal("0")
    assert Decimal(so.json()["data"]["lines"][0]["qty_reserved"]) == Decimal("5")


@pytest.mark.asyncio
async def test_deliverable_lines_and_tracker(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _receive_stock(client, headers, quantity="3")
    product_id = str(ctx["product_id"])
    order = await _confirm_sales_order(client, headers, product_id=product_id, quantity="3")
    deliverable = await client.get(
        f"/api/v1/sales-orders/{order['id']}/deliverable-lines", headers=headers
    )
    assert deliverable.status_code == 200, deliverable.text
    lines = deliverable.json()["data"]
    assert len(lines) == 1
    assert Decimal(lines[0]["outstanding"]) == Decimal("3")

    note = await _create_and_post_delivery_note(client, headers, order["id"])
    tracker = await client.get(f"/api/v1/sales-orders/{order['id']}/tracker", headers=headers)
    assert tracker.status_code == 200, tracker.text
    stages = {row["stage"] for row in tracker.json()["data"]["rows"]}
    assert "sales_order" in stages
    assert "delivery_note" in stages
    assert any(row["document_id"] == note["id"] for row in tracker.json()["data"]["rows"])

"""API tests for delivery notes created from posted sales invoices."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.sales_orders.test_routes import _create_customer
from tests.api.inventory_management.delivery_notes.test_routes import (
    _idempotent,
    _receive_stock,
)
from tests.conftest import login_headers, provision_admin


async def _enable_books(client: AsyncClient, headers: dict[str, str]) -> None:
    today = datetime.now(UTC).date().isoformat()
    updated = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"books_start_date": today},
    )
    assert updated.status_code == 200, updated.text


async def _posted_sales_invoice_without_delivery(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    quantity: str = "10",
) -> dict[str, object]:
    ctx = await _receive_stock(client, headers, quantity=quantity)
    product_id = str(ctx["product_id"])
    customer_id = await _create_customer(client, headers, trn=f"200{uuid4().int % 10**12:012d}")
    created = await client.post(
        "/api/v1/sales-invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "lines": [{"product_id": product_id, "quantity": quantity}],
        },
    )
    assert created.status_code == 201, created.text
    invoice = created.json()["data"]
    posted = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/post",
        headers=_idempotent(headers, invoice["version"]),
    )
    assert posted.status_code == 200, posted.text
    return posted.json()["data"]


@pytest.mark.asyncio
async def test_from_posted_invoice_creates_note_and_tracks_qty_delivered(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    invoice = await _posted_sales_invoice_without_delivery(client, headers, quantity="10")

    created = await client.post(
        "/api/v1/delivery-notes/from-sales-invoice",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"sales_invoice_id": invoice["id"]},
    )
    assert created.status_code == 201, created.text
    note = created.json()["data"]
    assert note["status"] == "DRAFT"
    assert note["source_sales_invoice_id"] == invoice["id"]
    assert note["sales_order_id"] is None
    assert Decimal(note["lines"][0]["quantity"]) == Decimal("10")

    posted = await client.post(
        f"/api/v1/delivery-notes/{note['id']}/post",
        headers=_idempotent(headers, note["version"]),
    )
    assert posted.status_code == 200, posted.text

    si = await client.get(f"/api/v1/sales-invoices/{invoice['id']}", headers=headers)
    assert si.status_code == 200, si.text
    assert Decimal(si.json()["data"]["lines"][0]["qty_delivered"]) == Decimal("10")

    related = si.json()["data"]["related_documents"]
    assert any(
        row["document_type"] == "DELIVERY_NOTE" and row["document_id"] == note["id"]
        for row in related
    )

    over = await client.post(
        "/api/v1/delivery-notes/from-sales-invoice",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"sales_invoice_id": invoice["id"]},
    )
    assert over.status_code == 422, over.text

    partial_invoice = await _posted_sales_invoice_without_delivery(client, headers, quantity="6")
    partial_line_id = partial_invoice["lines"][0]["id"]
    partial = await client.post(
        "/api/v1/delivery-notes/from-sales-invoice",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={
            "sales_invoice_id": partial_invoice["id"],
            "lines": [{"source_line_id": partial_line_id, "quantity": "2"}],
        },
    )
    assert partial.status_code == 201, partial.text
    assert Decimal(partial.json()["data"]["lines"][0]["quantity"]) == Decimal("2")

    over_line = await client.post(
        "/api/v1/delivery-notes/from-sales-invoice",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={
            "sales_invoice_id": partial_invoice["id"],
            "lines": [{"source_line_id": partial_line_id, "quantity": "10"}],
        },
    )
    assert over_line.status_code == 422, over_line.text


@pytest.mark.asyncio
async def test_invoice_only_draft_update_preserves_source_line(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    invoice = await _posted_sales_invoice_without_delivery(client, headers, quantity="10")
    source_line_id = invoice["lines"][0]["id"]

    created = await client.post(
        "/api/v1/delivery-notes/from-sales-invoice",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"sales_invoice_id": invoice["id"]},
    )
    assert created.status_code == 201, created.text
    note = created.json()["data"]

    updated = await client.patch(
        f"/api/v1/delivery-notes/{note['id']}",
        headers=_idempotent(headers, note["version"]),
        json={
            "version": note["version"],
            "notes": "Updated before delivery",
            "lines": [
                {
                    "source_sales_invoice_line_id": source_line_id,
                    "product_id": note["lines"][0]["product_id"],
                    "description": note["lines"][0]["description"],
                    "quantity": "8",
                    "unit_id": note["lines"][0]["unit_id"],
                    "rate": note["lines"][0]["rate"],
                }
            ],
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()["data"]
    assert body["notes"] == "Updated before delivery"
    assert body["source_sales_invoice_id"] == invoice["id"]
    assert body["sales_order_id"] is None
    assert Decimal(body["lines"][0]["quantity"]) == Decimal("8")
    assert body["lines"][0]["source_sales_invoice_line_id"] == source_line_id


@pytest.mark.asyncio
async def test_sales_return_from_invoice_only_delivery_note(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    invoice = await _posted_sales_invoice_without_delivery(client, headers, quantity="6")
    product_id = invoice["lines"][0]["product_id"]

    created = await client.post(
        "/api/v1/delivery-notes/from-sales-invoice",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"sales_invoice_id": invoice["id"]},
    )
    assert created.status_code == 201, created.text
    note = created.json()["data"]
    posted = await client.post(
        f"/api/v1/delivery-notes/{note['id']}/post",
        headers=_idempotent(headers, note["version"]),
    )
    assert posted.status_code == 200, posted.text
    posted_note = posted.json()["data"]
    dn_line = posted_note["lines"][0]

    created_return = await client.post(
        "/api/v1/sales-returns",
        headers=headers,
        json={
            "delivery_note_id": posted_note["id"],
            "reason_code": "WRONG_ITEM_SHIPPED",
            "lines": [
                {
                    "delivery_note_line_id": dn_line["id"],
                    "product_id": product_id,
                    "quantity": "2",
                    "disposition": "RESTOCK",
                }
            ],
        },
    )
    assert created_return.status_code == 201, created_return.text
    sales_return = created_return.json()["data"]
    assert sales_return["sales_order_id"] is None

    posted_return = await client.post(
        f"/api/v1/sales-returns/{sales_return['id']}/post",
        headers=_idempotent(headers, sales_return["version"]),
    )
    assert posted_return.status_code == 200, posted_return.text

    stock = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    assert stock.status_code == 200, stock.text
    row = stock.json()["data"][0]
    assert Decimal(row["qty_on_hand"]) == Decimal("2")

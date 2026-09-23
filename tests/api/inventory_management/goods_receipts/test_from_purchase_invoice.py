"""API tests for goods receipts created from posted purchase invoices."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.inventory_management.delivery_notes.test_routes import _idempotent
from tests.api.inventory_management.goods_receipts.test_routes import _issue_tracked_po
from tests.conftest import login_headers, provision_admin


async def _enable_books(client: AsyncClient, headers: dict[str, str]) -> None:
    today = datetime.now(UTC).date().isoformat()
    updated = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"books_start_date": today},
    )
    assert updated.status_code == 200, updated.text


async def _posted_purchase_invoice_without_receipt(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    quantity: str = "10",
) -> dict[str, object]:
    ctx = await _issue_tracked_po(client, headers, quantity=quantity)
    created = await client.post(
        "/api/v1/purchase-invoices/from-purchase-order",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"purchase_order_id": ctx["order"]["id"]},
    )
    assert created.status_code == 201, created.text
    invoice = created.json()["data"]
    posted = await client.post(
        f"/api/v1/purchase-invoices/{invoice['id']}/post",
        headers=_idempotent(headers, invoice["version"]),
    )
    assert posted.status_code == 200, posted.text
    return posted.json()["data"]


@pytest.mark.asyncio
async def test_from_posted_bill_creates_receipt_and_tracks_qty_received(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    invoice = await _posted_purchase_invoice_without_receipt(client, headers, quantity="10")
    line_id = invoice["lines"][0]["id"]

    created = await client.post(
        "/api/v1/goods-receipts/from-purchase-invoice",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"purchase_invoice_id": invoice["id"]},
    )
    assert created.status_code == 201, created.text
    receipt = created.json()["data"]
    assert receipt["status"] == "DRAFT"
    assert receipt["source_purchase_invoice_id"] == invoice["id"]
    assert receipt["purchase_order_id"] == invoice["purchase_order_id"]
    assert Decimal(receipt["lines"][0]["quantity"]) == Decimal("10")

    posted = await client.post(
        f"/api/v1/goods-receipts/{receipt['id']}/post",
        headers=_idempotent(headers, receipt["version"]),
    )
    assert posted.status_code == 200, posted.text

    pi = await client.get(f"/api/v1/purchase-invoices/{invoice['id']}", headers=headers)
    assert pi.status_code == 200, pi.text
    assert Decimal(pi.json()["data"]["lines"][0]["qty_received"]) == Decimal("10")

    related = pi.json()["data"]["related_documents"]
    assert any(
        row["document_type"] == "GOODS_RECEIPT" and row["document_id"] == receipt["id"]
        for row in related
    )

    over = await client.post(
        "/api/v1/goods-receipts/from-purchase-invoice",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"purchase_invoice_id": invoice["id"]},
    )
    assert over.status_code == 422, over.text

    partial_invoice = await _posted_purchase_invoice_without_receipt(client, headers, quantity="6")
    partial_line_id = partial_invoice["lines"][0]["id"]
    partial = await client.post(
        "/api/v1/goods-receipts/from-purchase-invoice",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={
            "purchase_invoice_id": partial_invoice["id"],
            "lines": [{"source_line_id": partial_line_id, "quantity": "2"}],
        },
    )
    assert partial.status_code == 201, partial.text
    assert Decimal(partial.json()["data"]["lines"][0]["quantity"]) == Decimal("2")

    over_line = await client.post(
        "/api/v1/goods-receipts/from-purchase-invoice",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={
            "purchase_invoice_id": partial_invoice["id"],
            "lines": [{"source_line_id": partial_line_id, "quantity": "10"}],
        },
    )
    assert over_line.status_code == 422, over_line.text


@pytest.mark.asyncio
async def test_invoice_sourced_draft_update_preserves_source_line(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    invoice = await _posted_purchase_invoice_without_receipt(client, headers, quantity="10")
    source_line_id = invoice["lines"][0]["id"]

    created = await client.post(
        "/api/v1/goods-receipts/from-purchase-invoice",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"purchase_invoice_id": invoice["id"]},
    )
    assert created.status_code == 201, created.text
    receipt = created.json()["data"]

    updated = await client.patch(
        f"/api/v1/goods-receipts/{receipt['id']}",
        headers=_idempotent(headers, receipt["version"]),
        json={
            "version": receipt["version"],
            "notes": "Updated before receive",
            "lines": [
                {
                    "source_purchase_invoice_line_id": source_line_id,
                    "purchase_order_line_id": receipt["lines"][0]["purchase_order_line_id"],
                    "product_id": receipt["lines"][0]["product_id"],
                    "description": receipt["lines"][0]["description"],
                    "quantity": "7",
                    "unit_id": receipt["lines"][0]["unit_id"],
                    "rate": receipt["lines"][0]["rate"],
                }
            ],
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()["data"]
    assert body["notes"] == "Updated before receive"
    assert body["source_purchase_invoice_id"] == invoice["id"]
    assert Decimal(body["lines"][0]["quantity"]) == Decimal("7")
    assert body["lines"][0]["source_purchase_invoice_line_id"] == source_line_id

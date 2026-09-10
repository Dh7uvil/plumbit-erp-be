"""API tests for sales invoices: create, post, void, and double-invoice guard."""

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


async def _enable_books(client: AsyncClient, headers: dict[str, str]) -> None:
    today = datetime.now(UTC).date().isoformat()
    updated = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"books_start_date": today},
    )
    assert updated.status_code == 200, updated.text


@pytest.mark.asyncio
async def test_create_from_sales_order_and_post_writes_ar_journal(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    ctx = await _receive_stock(client, headers, quantity="2")
    product_id = str(ctx["product_id"])
    order = await _confirm_sales_order(client, headers, product_id=product_id, quantity="2")
    created = await client.post(
        "/api/v1/sales-invoices/from-sales-order",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"sales_order_id": order["id"]},
    )
    assert created.status_code == 201, created.text
    invoice = created.json()["data"]
    assert invoice["status"] == "DRAFT"
    assert invoice["sales_order_id"] == order["id"]
    assert Decimal(invoice["subtotal"]) == Decimal("200.0000")
    assert Decimal(invoice["tax_amount"]) == Decimal("10.0000")
    assert Decimal(invoice["grand_total"]) == Decimal("210.0000")
    assert invoice["cogs_status"] == "NOT_APPLICABLE"

    posted = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/post",
        headers=_idempotent(headers, invoice["version"]),
    )
    assert posted.status_code == 200, posted.text
    data = posted.json()["data"]
    assert data["status"] == "POSTED"
    assert data["is_posted"] is True
    assert data["journal_entry_id"]
    assert data["cogs_status"] == "PENDING"
    assert Decimal(data["cogs_amount"]) == Decimal("0.0000")
    assert Decimal(data["balance_due"]) == Decimal("210.0000")
    assert data["payment_status"] == "UNPAID"

    so = await client.get(f"/api/v1/sales-orders/{order['id']}", headers=headers)
    assert so.json()["data"]["billing_status"] == "INVOICED"
    assert Decimal(so.json()["data"]["lines"][0]["qty_invoiced"]) == Decimal("2")

    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    mapped = {item["role"]: item["account_id"] for item in roles.json()["data"]}
    journal = await client.get(
        f"/api/v1/sales-invoices/{invoice['id']}/journal", headers=headers
    )
    assert journal.status_code == 200, journal.text
    lines = journal.json()["data"]["lines"]
    by_account = {line["account_id"]: line for line in lines}
    ar = by_account[mapped["ACCOUNTS_RECEIVABLE"]]
    revenue = by_account[mapped["SALES_REVENUE"]]
    vat = by_account[mapped["VAT_OUTPUT"]]
    assert Decimal(ar["debit"]) == Decimal("210.0000")
    assert Decimal(revenue["credit"]) == Decimal("200.0000")
    assert Decimal(vat["credit"]) == Decimal("10.0000")
    assert mapped["COGS"] not in by_account
    assert mapped["INVENTORY"] not in by_account

    tracker = await client.get(f"/api/v1/sales-orders/{order['id']}/tracker", headers=headers)
    assert tracker.status_code == 200, tracker.text
    invoice_rows = [
        row
        for row in tracker.json()["data"]["rows"]
        if row["stage"] == "sales_invoice"
    ]
    assert len(invoice_rows) == 1
    assert invoice_rows[0]["document_id"] == data["id"]
    assert invoice_rows[0]["status"] == "POSTED"
    assert invoice_rows[0]["document_number"] == data["document_number"]

    duplicate = await client.post(
        "/api/v1/sales-invoices/from-sales-order",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"sales_order_id": order["id"]},
    )
    assert duplicate.status_code == 422, duplicate.text


@pytest.mark.asyncio
async def test_from_delivery_note_stamps_cogs_and_blocks_second_invoice(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    ctx = await _receive_stock(client, headers, quantity="4")
    product_id = str(ctx["product_id"])
    order = await _confirm_sales_order(client, headers, product_id=product_id, quantity="4")
    note = await _create_and_post_delivery_note(client, headers, order["id"])
    created = await client.post(
        "/api/v1/sales-invoices/from-delivery-notes",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"delivery_note_ids": [note["id"]]},
    )
    assert created.status_code == 201, created.text
    invoice = created.json()["data"]
    posted = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/post",
        headers=_idempotent(headers, invoice["version"]),
    )
    assert posted.status_code == 200, posted.text
    data = posted.json()["data"]
    assert data["cogs_status"] == "POSTED"
    assert Decimal(data["cogs_amount"]) > Decimal("0")
    assert data["lines"][0]["delivery_note_id"] == note["id"]

    dn = await client.get(f"/api/v1/delivery-notes/{note['id']}", headers=headers)
    assert Decimal(dn.json()["data"]["lines"][0]["qty_invoiced"]) == Decimal("4")

    second = await client.post(
        "/api/v1/sales-invoices/from-delivery-notes",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"delivery_note_ids": [note["id"]]},
    )
    assert second.status_code == 422, second.text

    cancel_dn = await client.post(
        f"/api/v1/delivery-notes/{note['id']}/cancel",
        headers=_idempotent(headers, dn.json()["data"]["version"]),
        json={"reason": "Already billed"},
    )
    assert cancel_dn.status_code == 409, cancel_dn.text


@pytest.mark.asyncio
async def test_void_posted_invoice_reverses_journal_and_qty(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    ctx = await _receive_stock(client, headers, quantity="2")
    product_id = str(ctx["product_id"])
    order = await _confirm_sales_order(client, headers, product_id=product_id, quantity="2")
    created = await client.post(
        "/api/v1/sales-invoices/from-sales-order",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"sales_order_id": order["id"]},
    )
    invoice = created.json()["data"]
    posted = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/post",
        headers=_idempotent(headers, invoice["version"]),
    )
    assert posted.status_code == 200, posted.text
    cancelled = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/cancel",
        headers=_idempotent(headers, posted.json()["data"]["version"]),
        json={"reason": "Posted in error"},
    )
    assert cancelled.status_code == 200, cancelled.text
    data = cancelled.json()["data"]
    assert data["status"] == "CANCELLED"
    assert data["reversal_journal_entry_id"]
    so = await client.get(f"/api/v1/sales-orders/{order['id']}", headers=headers)
    assert so.json()["data"]["billing_status"] == "NOT_INVOICED"
    assert Decimal(so.json()["data"]["lines"][0]["qty_invoiced"]) == Decimal("0")


@pytest.mark.asyncio
async def test_export_invoice_posts_without_vat_and_records_evidence_gap(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    ids_resp = await client.get("/api/v1/currencies?is_base=true", headers=headers)
    aed = ids_resp.json()["data"][0]["id"]
    taxes = await client.get("/api/v1/taxes?page_size=100", headers=headers)
    standard = next(item for item in taxes.json()["data"] if item["tax_category"] == "STANDARD")
    units = await client.get("/api/v1/units?page_size=100", headers=headers)
    pcs = next(item for item in units.json()["data"] if item["code"] == "PCS")
    customer = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "name": "Export Buyer",
            "code": f"EX-{uuid4().hex[:8]}",
            "tax_treatment": "EXPORT",
            "shipping_address": {
                "address_line_1": "Port",
                "city": "Mumbai",
                "state": "MH",
                "country_code": "IN",
                "country": "India",
            },
            "billing_address": {
                "address_line_1": "Port",
                "city": "Mumbai",
                "state": "MH",
                "country_code": "IN",
                "country": "India",
            },
        },
    )
    assert customer.status_code == 201, customer.text
    product = await client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "sku": f"SKU-{uuid4().hex[:8]}",
            "name": "Export pipe",
            "unit_id": pcs["id"],
            "selling_rate": "100.0000",
            "tax_id": standard["id"],
        },
    )
    assert product.status_code == 201, product.text
    created = await client.post(
        "/api/v1/sales-invoices",
        headers=headers,
        json={
            "customer_id": customer.json()["data"]["id"],
            "currency_id": aed,
            "lines": [
                {
                    "product_id": product.json()["data"]["id"],
                    "quantity": "2",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    invoice = created.json()["data"]
    assert invoice["is_export"] is True
    assert Decimal(invoice["tax_amount"]) == Decimal("0.0000")
    posted = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/post",
        headers=_idempotent(headers, invoice["version"]),
    )
    assert posted.status_code == 200, posted.text
    data = posted.json()["data"]
    assert data["export_evidence_ok"] is False
    assert posted.json()["meta"].get("export_evidence_ok") is False
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    mapped = {item["role"]: item["account_id"] for item in roles.json()["data"]}
    journal = await client.get(
        f"/api/v1/sales-invoices/{invoice['id']}/journal", headers=headers
    )
    accounts = {line["account_id"] for line in journal.json()["data"]["lines"]}
    assert mapped["VAT_OUTPUT"] not in accounts

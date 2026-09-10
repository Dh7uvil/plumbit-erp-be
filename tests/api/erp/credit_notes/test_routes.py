"""API tests for credit notes: from posted SI, journal reversal, qty cap, void block."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.inventory_management.delivery_notes.test_routes import (
    _confirm_sales_order,
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


async def _posted_sales_invoice(client: AsyncClient, headers: dict[str, str]) -> dict[str, object]:
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
    posted = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/post",
        headers=_idempotent(headers, invoice["version"]),
    )
    assert posted.status_code == 200, posted.text
    return posted.json()["data"]


@pytest.mark.asyncio
async def test_from_posted_invoice_post_reverses_ar_and_blocks_void(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    invoice = await _posted_sales_invoice(client, headers)

    created = await client.post(
        "/api/v1/credit-notes/from-sales-invoice",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"sales_invoice_id": invoice["id"]},
    )
    assert created.status_code == 201, created.text
    note = created.json()["data"]
    assert note["status"] == "DRAFT"
    assert note["sales_invoice_id"] == invoice["id"]
    assert Decimal(note["grand_total"]) == Decimal(str(invoice["grand_total"]))

    posted = await client.post(
        f"/api/v1/credit-notes/{note['id']}/post",
        headers=_idempotent(headers, note["version"]),
    )
    assert posted.status_code == 200, posted.text
    data = posted.json()["data"]
    assert data["status"] == "POSTED"
    assert data["is_posted"] is True
    assert data["journal_entry_id"]
    assert Decimal(data["amount_applied"]) == Decimal(str(data["grand_total"]))
    assert Decimal(data["amount_unapplied"]) == Decimal("0")

    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    mapped = {item["role"]: item["account_id"] for item in roles.json()["data"]}
    journal = await client.get(f"/api/v1/credit-notes/{data['id']}/journal", headers=headers)
    assert journal.status_code == 200, journal.text
    by_account = {line["account_id"]: line for line in journal.json()["data"]["lines"]}
    ar = by_account[mapped["ACCOUNTS_RECEIVABLE"]]
    revenue = by_account[mapped["SALES_REVENUE"]]
    vat = by_account[mapped["VAT_OUTPUT"]]
    assert Decimal(ar["credit"]) == Decimal(str(invoice["grand_total"]))
    assert Decimal(revenue["debit"]) == Decimal(str(invoice["subtotal"]))
    assert Decimal(vat["debit"]) == Decimal(str(invoice["tax_amount"]))
    assert mapped["COGS"] not in by_account
    assert mapped["INVENTORY"] not in by_account

    si = await client.get(f"/api/v1/sales-invoices/{invoice['id']}", headers=headers)
    si_data = si.json()["data"]
    assert Decimal(si_data["amount_credited"]) == Decimal(str(data["grand_total"]))
    assert Decimal(si_data["lines"][0]["qty_credited"]) == Decimal(
        str(si_data["lines"][0]["quantity"])
    )

    second = await client.post(
        "/api/v1/credit-notes/from-sales-invoice",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"sales_invoice_id": invoice["id"]},
    )
    assert second.status_code == 422, second.text

    voided = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/cancel",
        headers=_idempotent(headers, si_data["version"]),
        json={"reason": "Has a live credit note"},
    )
    assert voided.status_code == 409, voided.text

"""Phase 6 — payment allocation hardening."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.customer_payments.test_routes import (
    _accounts,
    _create_product,
    _enable_books,
    _idempotent,
    _posted_invoice,
    _seeded_ids,
)
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_unapply_posted_allocation_restores_unapplied(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    invoice = await _posted_invoice(client, headers)
    total = Decimal(str(invoice["grand_total"]))
    created = await client.post(
        "/api/v1/customer-payments",
        headers=headers,
        json={
            "customer_id": invoice["customer_id"],
            "currency_id": invoice["currency_id"],
            "amount_received": str(total),
            "payment_account_id": accounts["BANK"],
        },
    )
    assert created.status_code == 201, created.text
    payment = created.json()["data"]
    posted = await client.post(
        f"/api/v1/customer-payments/{payment['id']}/post",
        headers=_idempotent(headers, payment["version"]),
    )
    assert posted.status_code == 200, posted.text
    body = posted.json()["data"]
    assert Decimal(body["amount_unapplied"]) == total
    apply_slice = total / 2
    allocated = await client.post(
        f"/api/v1/customer-payments/{payment['id']}/allocate",
        headers={**headers, "If-Match": str(body["version"])},
        json={
            "version": body["version"],
            "allocations": [
                {
                    "item_type": "SALES_INVOICE",
                    "item_id": invoice["id"],
                    "amount": str(apply_slice),
                }
            ],
        },
    )
    assert allocated.status_code == 200, allocated.text
    body = allocated.json()["data"]
    history = await client.get(
        f"/api/v1/customer-payments/{payment['id']}/allocations", headers=headers
    )
    assert history.status_code == 200, history.text
    allocation = next(row for row in history.json()["data"] if row["journal_entry_id"])
    unapplied = await client.delete(
        f"/api/v1/customer-payments/{payment['id']}/allocations/{allocation['id']}",
        headers={
            **headers,
            "If-Match": str(body["version"]),
            "Idempotency-Key": uuid4().hex,
        },
    )
    assert unapplied.status_code == 200, unapplied.text
    after = unapplied.json()["data"]
    assert Decimal(after["amount_unapplied"]) == total
    invoice_after = await client.get(f"/api/v1/sales-invoices/{invoice['id']}", headers=headers)
    assert Decimal(invoice_after.json()["data"]["balance_due"]) == total


@pytest.mark.asyncio
async def test_unapply_allocation_from_post_draft_allocations(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    invoice = await _posted_invoice(client, headers)
    total = Decimal(str(invoice["grand_total"]))
    created = await client.post(
        "/api/v1/customer-payments",
        headers=headers,
        json={
            "customer_id": invoice["customer_id"],
            "currency_id": invoice["currency_id"],
            "amount_received": str(total),
            "payment_account_id": accounts["BANK"],
            "allocations": [
                {
                    "item_type": "SALES_INVOICE",
                    "item_id": invoice["id"],
                    "amount": str(total),
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    payment = created.json()["data"]
    posted = await client.post(
        f"/api/v1/customer-payments/{payment['id']}/post",
        headers=_idempotent(headers, payment["version"]),
    )
    assert posted.status_code == 200, posted.text
    body = posted.json()["data"]
    assert Decimal(body["amount_unapplied"]) == Decimal("0")
    history = await client.get(
        f"/api/v1/customer-payments/{payment['id']}/allocations", headers=headers
    )
    assert history.status_code == 200, history.text
    allocation = next(row for row in history.json()["data"] if not row.get("reversed_at"))
    assert allocation["journal_entry_id"] is not None
    unapplied = await client.delete(
        f"/api/v1/customer-payments/{payment['id']}/allocations/{allocation['id']}",
        headers={
            **headers,
            "If-Match": str(body["version"]),
            "Idempotency-Key": uuid4().hex,
        },
    )
    assert unapplied.status_code == 200, unapplied.text
    after = unapplied.json()["data"]
    assert Decimal(after["amount_unapplied"]) == total
    invoice_after = await client.get(f"/api/v1/sales-invoices/{invoice['id']}", headers=headers)
    assert Decimal(invoice_after.json()["data"]["balance_due"]) == total


@pytest.mark.asyncio
async def test_receipt_nets_credit_note_with_invoice_on_post(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    ids = await _seeded_ids(client, headers)
    invoice = await _posted_invoice(client, headers)
    product_id = await _create_product(client, headers, ids)
    note = await client.post(
        "/api/v1/credit-notes",
        headers=headers,
        json={
            "customer_id": invoice["customer_id"],
            "reason_code": "PRICE_ADJUSTMENT",
            "lines": [{"product_id": product_id, "quantity": "1", "rate": "20.0000"}],
        },
    )
    assert note.status_code == 201, note.text
    note_row = note.json()["data"]
    posted_note = await client.post(
        f"/api/v1/credit-notes/{note_row['id']}/post",
        headers=_idempotent(headers, note_row["version"]),
    )
    assert posted_note.status_code == 200, posted_note.text
    credit_amount = Decimal("20.0000")
    invoice_total = Decimal(str(invoice["grand_total"]))
    cash = invoice_total - credit_amount
    created = await client.post(
        "/api/v1/customer-payments",
        headers=headers,
        json={
            "customer_id": invoice["customer_id"],
            "currency_id": invoice["currency_id"],
            "amount_received": str(cash),
            "payment_account_id": accounts["BANK"],
            "allocations": [
                {
                    "item_type": "SALES_INVOICE",
                    "item_id": invoice["id"],
                    "amount": str(cash),
                },
                {
                    "item_type": "CREDIT_NOTE",
                    "item_id": note_row["id"],
                    "amount": str(credit_amount),
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    payment = created.json()["data"]
    posted = await client.post(
        f"/api/v1/customer-payments/{payment['id']}/post",
        headers=_idempotent(headers, payment["version"]),
    )
    assert posted.status_code == 200, posted.text
    settled = await client.get(f"/api/v1/sales-invoices/{invoice['id']}", headers=headers)
    assert Decimal(settled.json()["data"]["balance_due"]) == Decimal("0")
    history = await client.get(
        f"/api/v1/customer-payments/{payment['id']}/allocations", headers=headers
    )
    assert history.status_code == 200, history.text
    rows = history.json()["data"]
    note_rows = [
        row for row in rows if row["item_type"] == "CREDIT_NOTE" and not row["reversed_at"]
    ]
    assert len(note_rows) == 1
    assert note_rows[0]["item_id"] == note_row["id"]
    assert Decimal(note_rows[0]["amount"]) == credit_amount
    assert note_rows[0]["journal_entry_id"] is None
    cash_rows = [
        row for row in rows if row["item_type"] == "SALES_INVOICE" and not row["reversed_at"]
    ]
    assert len(cash_rows) == 1
    assert cash_rows[0]["journal_entry_id"] is not None


@pytest.mark.asyncio
async def test_period_lock_blocks_unapply(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    invoice = await _posted_invoice(client, headers)
    total = Decimal(str(invoice["grand_total"]))
    created = await client.post(
        "/api/v1/customer-payments",
        headers=headers,
        json={
            "customer_id": invoice["customer_id"],
            "currency_id": invoice["currency_id"],
            "amount_received": str(total),
            "payment_account_id": accounts["BANK"],
        },
    )
    assert created.status_code == 201, created.text
    payment = created.json()["data"]
    posted = await client.post(
        f"/api/v1/customer-payments/{payment['id']}/post",
        headers=_idempotent(headers, payment["version"]),
    )
    assert posted.status_code == 200, posted.text
    body = posted.json()["data"]
    allocated = await client.post(
        f"/api/v1/customer-payments/{payment['id']}/allocate",
        headers={**headers, "If-Match": str(body["version"])},
        json={
            "version": body["version"],
            "allocations": [
                {
                    "item_type": "SALES_INVOICE",
                    "item_id": invoice["id"],
                    "amount": str(total),
                }
            ],
        },
    )
    assert allocated.status_code == 200, allocated.text
    body = allocated.json()["data"]
    history = await client.get(
        f"/api/v1/customer-payments/{payment['id']}/allocations", headers=headers
    )
    allocation = next(row for row in history.json()["data"] if row["journal_entry_id"])
    locked = await client.patch(
        "/api/v1/period-lock",
        headers=headers,
        json={"hard_lock_date": datetime.now(UTC).date().isoformat()},
    )
    assert locked.status_code == 200, locked.text
    denied = await client.delete(
        f"/api/v1/customer-payments/{payment['id']}/allocations/{allocation['id']}",
        headers={
            **headers,
            "If-Match": str(body["version"]),
            "Idempotency-Key": uuid4().hex,
        },
    )
    assert denied.status_code == 409, denied.text


@pytest.mark.asyncio
async def test_stale_version_blocks_second_allocate(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    invoice = await _posted_invoice(client, headers)
    total = Decimal(str(invoice["grand_total"]))
    created = await client.post(
        "/api/v1/customer-payments",
        headers=headers,
        json={
            "customer_id": invoice["customer_id"],
            "currency_id": invoice["currency_id"],
            "amount_received": str(total),
            "payment_account_id": accounts["BANK"],
        },
    )
    payment = created.json()["data"]
    posted = await client.post(
        f"/api/v1/customer-payments/{payment['id']}/post",
        headers=_idempotent(headers, payment["version"]),
    )
    body = posted.json()["data"]
    version = body["version"]
    slice_amount = total / 2
    first = await client.post(
        f"/api/v1/customer-payments/{payment['id']}/allocate",
        headers={**headers, "If-Match": str(version)},
        json={
            "version": version,
            "allocations": [
                {
                    "item_type": "SALES_INVOICE",
                    "item_id": invoice["id"],
                    "amount": str(slice_amount),
                }
            ],
        },
    )
    assert first.status_code == 200, first.text
    stale = await client.post(
        f"/api/v1/customer-payments/{payment['id']}/allocate",
        headers={**headers, "If-Match": str(version)},
        json={
            "version": version,
            "allocations": [
                {
                    "item_type": "SALES_INVOICE",
                    "item_id": invoice["id"],
                    "amount": str(slice_amount),
                }
            ],
        },
    )
    assert stale.status_code == 409, stale.text


@pytest.mark.asyncio
async def test_allocate_rejects_over_application(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    invoice = await _posted_invoice(client, headers)
    total = Decimal(str(invoice["grand_total"]))
    created = await client.post(
        "/api/v1/customer-payments",
        headers=headers,
        json={
            "customer_id": invoice["customer_id"],
            "currency_id": invoice["currency_id"],
            "amount_received": str(total),
            "payment_account_id": accounts["BANK"],
        },
    )
    payment = created.json()["data"]
    posted = await client.post(
        f"/api/v1/customer-payments/{payment['id']}/post",
        headers=_idempotent(headers, payment["version"]),
    )
    body = posted.json()["data"]
    denied = await client.post(
        f"/api/v1/customer-payments/{payment['id']}/allocate",
        headers={**headers, "If-Match": str(body["version"])},
        json={
            "version": body["version"],
            "allocations": [
                {
                    "item_type": "SALES_INVOICE",
                    "item_id": invoice["id"],
                    "amount": str(total + Decimal("1")),
                }
            ],
        },
    )
    assert denied.status_code == 422, denied.text


@pytest.mark.asyncio
async def test_list_allocations_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    await _enable_books(client, headers_a)
    accounts = await _accounts(client, headers_a)
    invoice = await _posted_invoice(client, headers_a)
    total = Decimal(str(invoice["grand_total"]))
    created = await client.post(
        "/api/v1/customer-payments",
        headers=headers_a,
        json={
            "customer_id": invoice["customer_id"],
            "currency_id": invoice["currency_id"],
            "amount_received": str(total),
            "payment_account_id": accounts["BANK"],
            "allocations": [
                {
                    "item_type": "SALES_INVOICE",
                    "item_id": invoice["id"],
                    "amount": str(total),
                }
            ],
        },
    )
    payment_id = created.json()["data"]["id"]
    posted = await client.post(
        f"/api/v1/customer-payments/{payment_id}/post",
        headers=_idempotent(headers_a, created.json()["data"]["version"]),
    )
    assert posted.status_code == 200, posted.text

    tenant_b, email_b, password_b = await provision_admin()
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    denied = await client.get(
        f"/api/v1/customer-payments/{payment_id}/allocations", headers=headers_b
    )
    assert denied.status_code == 404, denied.text

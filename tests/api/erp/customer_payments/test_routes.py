"""Customer receipts: allocation, advances, bank charges, and settlement."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.quotation.test_routes import _create_customer, _create_product, _seeded_ids
from tests.conftest import login_headers, provision_admin


def _idempotent(headers: dict[str, str], version: object) -> dict[str, str]:
    return {**headers, "If-Match": str(version), "Idempotency-Key": uuid4().hex}


async def _enable_books(client: AsyncClient, headers: dict[str, str]) -> str:
    today = datetime.now(UTC).date().isoformat()
    updated = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"books_start_date": today},
    )
    assert updated.status_code == 200, updated.text
    return today


async def _accounts(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    assert roles.status_code == 200, roles.text
    return {item["role"]: item["account_id"] for item in roles.json()["data"]}


async def _posted_invoice(
    client: AsyncClient, headers: dict[str, str], *, selling_rate: str = "100.0000"
) -> dict[str, object]:
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids, selling_rate=selling_rate)
    created = await client.post(
        "/api/v1/sales-invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "lines": [{"product_id": product_id, "quantity": "1"}],
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


async def _post_receipt(
    client: AsyncClient,
    headers: dict[str, str],
    payload: dict[str, object],
) -> dict[str, object]:
    created = await client.post("/api/v1/customer-payments", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    posted = await client.post(
        f"/api/v1/customer-payments/{row['id']}/post",
        headers=_idempotent(headers, row["version"]),
    )
    assert posted.status_code == 200, posted.text
    return posted.json()["data"]


@pytest.mark.asyncio
async def test_full_allocate_settles_invoice_and_blocks_void(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    invoice = await _posted_invoice(client, headers)
    total = Decimal(str(invoice["grand_total"]))
    receipt = await _post_receipt(
        client,
        headers,
        {
            "customer_id": invoice["customer_id"],
            "amount_received": str(total),
            "payment_account_id": accounts["BANK"],
            "payment_method": "BANK",
            "allocations": [
                {
                    "item_type": "SALES_INVOICE",
                    "item_id": invoice["id"],
                    "amount": str(total),
                }
            ],
        },
    )
    assert receipt["status"] == "POSTED"
    assert Decimal(receipt["amount_unapplied"]) == Decimal("0")
    fetched = await client.get(f"/api/v1/sales-invoices/{invoice['id']}", headers=headers)
    body = fetched.json()["data"]
    assert Decimal(body["amount_paid"]) == total
    assert Decimal(body["balance_due"]) == Decimal("0")
    assert body["payment_status"] == "PAID"
    assert "record_payment" not in body["available_actions"]
    voided = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/cancel",
        headers=_idempotent(headers, body["version"]),
    )
    assert voided.status_code == 409, voided.text
    journal = await client.get(
        f"/api/v1/customer-payments/{receipt['id']}/journal", headers=headers
    )
    assert journal.status_code == 200, journal.text
    by_account = {line["account_id"]: line for line in journal.json()["data"]["lines"]}
    assert Decimal(by_account[accounts["BANK"]]["debit"]) == total
    assert Decimal(by_account[accounts["ACCOUNTS_RECEIVABLE"]]["credit"]) == total


@pytest.mark.asyncio
async def test_partial_receipt_leaves_advance_and_cancel_restores_unpaid(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    invoice = await _posted_invoice(client, headers)
    total = Decimal(str(invoice["grand_total"]))
    allocated = Decimal("50.0000")
    receipt = await _post_receipt(
        client,
        headers,
        {
            "customer_id": invoice["customer_id"],
            "amount_received": str(total),
            "payment_account_id": accounts["BANK"],
            "allocations": [
                {
                    "item_type": "SALES_INVOICE",
                    "item_id": invoice["id"],
                    "amount": str(allocated),
                }
            ],
        },
    )
    leftover = total - allocated
    assert Decimal(receipt["amount_unapplied"]) == leftover
    fetched = await client.get(f"/api/v1/sales-invoices/{invoice['id']}", headers=headers)
    body = fetched.json()["data"]
    assert body["payment_status"] == "PARTIALLY_PAID"
    assert Decimal(body["balance_due"]) == leftover
    cancelled = await client.post(
        f"/api/v1/customer-payments/{receipt['id']}/cancel",
        headers=_idempotent(headers, receipt["version"]),
        json={"reason": "Posted to the wrong customer"},
    )
    assert cancelled.status_code == 200, cancelled.text
    restored = await client.get(f"/api/v1/sales-invoices/{invoice['id']}", headers=headers)
    restored_body = restored.json()["data"]
    assert restored_body["payment_status"] == "UNPAID"
    assert Decimal(restored_body["amount_paid"]) == Decimal("0")


@pytest.mark.asyncio
async def test_over_allocation_is_rejected(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    invoice = await _posted_invoice(client, headers)
    created = await client.post(
        "/api/v1/customer-payments",
        headers=headers,
        json={
            "customer_id": invoice["customer_id"],
            "amount_received": "10.0000",
            "payment_account_id": accounts["BANK"],
            "allocations": [
                {
                    "item_type": "SALES_INVOICE",
                    "item_id": invoice["id"],
                    "amount": "20.0000",
                }
            ],
        },
    )
    assert created.status_code == 422, created.text
    assert created.json()["error"]["code"] == "PAYMENT_OVER_ALLOCATED"


@pytest.mark.asyncio
async def test_bank_charges_and_idempotent_post(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    invoice = await _posted_invoice(client, headers)
    created = await client.post(
        "/api/v1/customer-payments",
        headers=headers,
        json={
            "customer_id": invoice["customer_id"],
            "amount_received": "50.0000",
            "bank_charges": "5.0000",
            "payment_account_id": accounts["BANK"],
            "payment_method": "TT",
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    key = uuid4().hex
    first = await client.post(
        f"/api/v1/customer-payments/{row['id']}/post",
        headers={**headers, "If-Match": str(row["version"]), "Idempotency-Key": key},
    )
    second = await client.post(
        f"/api/v1/customer-payments/{row['id']}/post",
        headers={**headers, "If-Match": str(row["version"]), "Idempotency-Key": key},
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    journal = await client.get(
        f"/api/v1/customer-payments/{row['id']}/journal", headers=headers
    )
    lines = journal.json()["data"]["lines"]
    bank_debit = sum(
        Decimal(line["debit"]) for line in lines if line["account_id"] == accounts["BANK"]
    )
    bank_credit = sum(
        Decimal(line["credit"]) for line in lines if line["account_id"] == accounts["BANK"]
    )
    assert bank_debit - bank_credit == Decimal("45.0000")
    charges = next(line for line in lines if line["account_id"] == accounts["BANK_CHARGES"])
    assert Decimal(charges["debit"]) == Decimal("5.0000")


@pytest.mark.asyncio
async def test_standalone_credit_apply_is_subledger_only(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    ids = await _seeded_ids(client, headers)
    invoice = await _posted_invoice(client, headers)
    created = await client.post(
        "/api/v1/credit-notes",
        headers=headers,
        json={
            "customer_id": invoice["customer_id"],
            "reason_code": "PRICE_ADJUSTMENT",
            "lines": [
                {
                    "product_id": await _create_product(client, headers, ids),
                    "quantity": "1",
                    "rate": "21.0000",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    note = created.json()["data"]
    posted_note = await client.post(
        f"/api/v1/credit-notes/{note['id']}/post",
        headers=_idempotent(headers, note["version"]),
    )
    assert posted_note.status_code == 200, posted_note.text
    note_body = posted_note.json()["data"]
    assert Decimal(note_body["amount_unapplied"]) == Decimal(str(note_body["grand_total"]))
    before = await client.get(f"/api/v1/credit-notes/{note['id']}/journal", headers=headers)
    before_lines = before.json()["data"]["lines"]
    invoice_journal = await client.get(
        f"/api/v1/sales-invoices/{invoice['id']}/journal", headers=headers
    )
    invoice_journal_id = invoice_journal.json()["data"]["id"]
    applied = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/apply-credits",
        headers={**headers, "If-Match": str(invoice["version"])},
        json={
            "allocations": [
                {
                    "item_type": "CREDIT_NOTE",
                    "item_id": note["id"],
                    "amount": str(note_body["grand_total"]),
                }
            ]
        },
    )
    assert applied.status_code == 200, applied.text
    after_invoice = applied.json()["data"]
    assert Decimal(after_invoice["amount_credited"]) == Decimal(str(note_body["grand_total"]))
    after_note = await client.get(f"/api/v1/credit-notes/{note['id']}/journal", headers=headers)
    assert after_note.json()["data"]["lines"] == before_lines
    after_invoice_journal = await client.get(
        f"/api/v1/sales-invoices/{invoice['id']}/journal", headers=headers
    )
    assert after_invoice_journal.json()["data"]["id"] == invoice_journal_id


@pytest.mark.asyncio
async def test_opening_ar_collection_and_aging_ties_to_trial_balance(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    today = datetime.now(UTC).date()
    customer_id = await _create_customer(client, headers)
    committed = await client.post(
        "/api/v1/opening-balances/commit",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={
            "books_start_date": today.isoformat(),
            "gl_lines": [],
            "ar_items": [
                {
                    "party_id": customer_id,
                    "amount": "80.0000",
                    "due_date": today.isoformat(),
                    "external_reference": "OB-AR-1",
                }
            ],
            "ap_items": [],
            "stock_lines": [],
        },
    )
    assert committed.status_code == 200, committed.text
    items = await client.get(f"/api/v1/customers/{customer_id}/open-items", headers=headers)
    assert items.status_code == 200, items.text
    opening = next(row for row in items.json()["data"] if row["item_type"] == "OPENING_AR")
    receipt = await _post_receipt(
        client,
        headers,
        {
            "customer_id": customer_id,
            "amount_received": "80.0000",
            "payment_account_id": accounts["BANK"],
            "allocations": [
                {
                    "item_type": "OPENING_AR",
                    "item_id": opening["document_id"],
                    "amount": "80.0000",
                }
            ],
        },
    )
    assert Decimal(receipt["amount_unapplied"]) == Decimal("0")
    remaining = await client.get(f"/api/v1/customers/{customer_id}/open-items", headers=headers)
    assert remaining.json()["data"] == []

    invoice = await _posted_invoice(client, headers)
    as_of = str(invoice["invoice_date"])
    aging = await client.get(
        "/api/v1/reports/ar-aging", headers=headers, params={"as_of": as_of}
    )
    assert aging.status_code == 200, aging.text
    tb = await client.get(
        "/api/v1/reports/trial-balance",
        headers=headers,
        params={"from": as_of, "to": as_of},
    )
    assert tb.status_code == 200, tb.text
    ar_line = next(
        line
        for line in tb.json()["data"]["lines"]
        if line["account_id"] == accounts["ACCOUNTS_RECEIVABLE"]
    )
    ar_net = Decimal(ar_line["closing_debit"]) - Decimal(ar_line["closing_credit"])
    assert Decimal(aging.json()["data"]["totals"]["total"]) == ar_net


@pytest.mark.asyncio
async def test_period_lock_blocks_receipt_post(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    invoice = await _posted_invoice(client, headers)
    created = await client.post(
        "/api/v1/customer-payments",
        headers=headers,
        json={
            "customer_id": invoice["customer_id"],
            "amount_received": "10.0000",
            "payment_account_id": accounts["BANK"],
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    locked = await client.patch(
        "/api/v1/period-lock",
        headers=headers,
        json={"hard_lock_date": datetime.now(UTC).date().isoformat()},
    )
    assert locked.status_code == 200, locked.text
    posted = await client.post(
        f"/api/v1/customer-payments/{row['id']}/post",
        headers=_idempotent(headers, row["version"]),
    )
    assert posted.status_code == 409, posted.text


@pytest.mark.asyncio
async def test_export_advance_has_no_vat_domestic_standard_does(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    ids = await _seeded_ids(client, headers)
    export_customer = await _create_customer(
        client,
        headers,
        tax_treatment="EXPORT",
        trn=None,
        shipping_country_code="CN",
        shipping_state="Guangdong",
    )
    export_receipt = await _post_receipt(
        client,
        headers,
        {
            "customer_id": export_customer,
            "amount_received": "105.0000",
            "payment_account_id": accounts["BANK"],
            "tax_id": ids["standard_tax"],
        },
    )
    export_journal = await client.get(
        f"/api/v1/customer-payments/{export_receipt['id']}/journal", headers=headers
    )
    export_accounts = {line["account_id"] for line in export_journal.json()["data"]["lines"]}
    assert accounts["VAT_OUTPUT"] not in export_accounts
    assert Decimal(export_receipt["tax_amount"]) == Decimal("0")

    domestic = await _create_customer(client, headers)
    domestic_receipt = await _post_receipt(
        client,
        headers,
        {
            "customer_id": domestic,
            "amount_received": "105.0000",
            "payment_account_id": accounts["BANK"],
            "tax_id": ids["standard_tax"],
        },
    )
    assert Decimal(domestic_receipt["tax_amount"]) == Decimal("5.0000")
    domestic_journal = await client.get(
        f"/api/v1/customer-payments/{domestic_receipt['id']}/journal", headers=headers
    )
    vat = next(
        line
        for line in domestic_journal.json()["data"]["lines"]
        if line["account_id"] == accounts["VAT_OUTPUT"]
    )
    assert Decimal(vat["credit"]) == Decimal("5.0000")


@pytest.mark.asyncio
async def test_pfi_advance_auto_settles_export_invoice(client: AsyncClient) -> None:
    from tests.api.erp.proforma_invoices.test_convert import _raise_pfi, _send_and_confirm_pfi
    from tests.api.erp.quotation.test_routes import _create_quote, _send_quote

    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(
        client,
        headers,
        tax_treatment="EXPORT",
        trn=None,
        shipping_country_code="CN",
        shipping_state="Guangdong",
    )
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    quote = await _send_quote(client, headers, created["body"]["data"])
    pfi = await _raise_pfi(client, headers, quote)
    confirmed = await _send_and_confirm_pfi(client, headers, pfi)
    advance = Decimal(str(confirmed["advance_required_amount"]))
    invoice_total = Decimal(str(confirmed["grand_total"]))
    assert Decimal(str(confirmed["tax_amount"])) == Decimal("0")
    receipt = await _post_receipt(
        client,
        headers,
        {
            "customer_id": customer_id,
            "amount_received": str(advance),
            "payment_account_id": accounts["BANK"],
            "payment_method": "TT",
            "proforma_invoice_id": confirmed["id"],
        },
    )
    assert Decimal(receipt["amount_unapplied"]) == advance
    assert Decimal(receipt["tax_amount"]) == Decimal("0")
    fetched_pfi = await client.get(f"/api/v1/proforma-invoices/{confirmed['id']}", headers=headers)
    assert Decimal(fetched_pfi.json()["data"]["advance_outstanding"]) == advance

    converted = await client.post(
        f"/api/v1/proforma-invoices/{confirmed['id']}/convert-to-sales-invoice",
        headers=_idempotent(headers, fetched_pfi.json()["data"]["version"]),
    )
    assert converted.status_code == 200, converted.text
    invoice = converted.json()["data"]
    posted = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/post",
        headers=_idempotent(headers, invoice["version"]),
    )
    assert posted.status_code == 200, posted.text
    body = posted.json()["data"]
    assert Decimal(body["tax_amount"]) == Decimal("0")
    assert Decimal(body["amount_paid"]) == advance
    assert Decimal(body["balance_due"]) == invoice_total - advance
    settled = await client.get(f"/api/v1/customer-payments/{receipt['id']}", headers=headers)
    assert Decimal(settled.json()["data"]["amount_unapplied"]) == Decimal("0")


@pytest.mark.asyncio
async def test_cny_sales_invoice_paid_later_books_fx(client: AsyncClient) -> None:
    from tests.api.erp.quotation.test_routes import _currency_id

    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    cny_id = await _currency_id(client, headers, "CNY")
    saved = await client.put(
        "/api/v1/exchange-rates",
        headers=headers,
        json={"currency_id": cny_id, "rate_to_base": "0.5000"},
    )
    assert saved.status_code == 200, saved.text
    customer_id = await _create_customer(
        client,
        headers,
        tax_treatment="UNREGISTERED",
        trn=None,
        currency_id=cny_id,
    )
    ids = await _seeded_ids(client, headers)
    product_id = await _create_product(client, headers, ids, selling_rate="100.0000")
    created = await client.post(
        "/api/v1/sales-invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "currency_id": cny_id,
            "lines": [{"product_id": product_id, "quantity": "1"}],
        },
    )
    assert created.status_code == 201, created.text
    invoice = created.json()["data"]
    posted = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/post",
        headers=_idempotent(headers, invoice["version"]),
    )
    assert posted.status_code == 200, posted.text
    updated = await client.put(
        "/api/v1/exchange-rates",
        headers=headers,
        json={"currency_id": cny_id, "rate_to_base": "0.5500"},
    )
    assert updated.status_code == 200, updated.text
    receipt = await _post_receipt(
        client,
        headers,
        {
            "customer_id": customer_id,
            "amount_received": str(posted.json()["data"]["grand_total"]),
            "currency_id": cny_id,
            "payment_account_id": accounts["BANK"],
            "allocations": [
                {
                    "item_type": "SALES_INVOICE",
                    "item_id": invoice["id"],
                    "amount": str(posted.json()["data"]["grand_total"]),
                }
            ],
        },
    )
    journal = await client.get(
        f"/api/v1/customer-payments/{receipt['id']}/journal", headers=headers
    )
    assert journal.status_code == 200, journal.text
    fx_lines = [
        line
        for line in journal.json()["data"]["lines"]
        if line["account_id"] == accounts["FX_GAIN_LOSS"]
    ]
    assert fx_lines
    fx_amount = sum(Decimal(line["debit"]) - Decimal(line["credit"]) for line in fx_lines)
    assert fx_amount != Decimal("0")

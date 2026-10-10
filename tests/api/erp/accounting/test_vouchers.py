"""Phase 7 — cash/bank vouchers and day book."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.api.erp.accounting.test_banking import _bank_account
from tests.api.erp.customer_payments.test_routes import (
    _enable_books,
    _idempotent,
    _posted_invoice,
)
from tests.conftest import login_headers, provision_admin


async def _account_by_subtype(client: AsyncClient, headers: dict[str, str], subtype: str) -> str:
    listed = await client.get("/api/v1/accounts", headers=headers)
    assert listed.status_code == 200, listed.text
    for row in listed.json()["data"]:
        if row.get("account_subtype") == subtype and not row.get("is_group"):
            return row["id"]
    raise AssertionError(f"{subtype} account not found")


async def _counter_account(client: AsyncClient, headers: dict[str, str]) -> str:
    listed = await client.get("/api/v1/accounts", headers=headers)
    assert listed.status_code == 200, listed.text
    skip = {"ACCOUNTS_RECEIVABLE", "ACCOUNTS_PAYABLE", "CASH", "BANK"}
    for row in listed.json()["data"]:
        if row.get("is_group"):
            continue
        if row.get("account_subtype") in skip:
            continue
        return row["id"]
    raise AssertionError("counter account not found")


async def _draft_cash_payment(
    client: AsyncClient, headers: dict[str, str], *, amount: str = "100"
) -> dict[str, object]:
    cash_account = await _account_by_subtype(client, headers, "CASH")
    counter_account = await _counter_account(client, headers)
    created = await client.post(
        "/api/v1/vouchers",
        headers=headers,
        json={
            "voucher_type": "CASH_PAYMENT",
            "payment_account_id": cash_account,
            "total_amount": amount,
            "payment_method": "CASH",
            "lines": [{"account_id": counter_account, "amount": amount}],
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]


@pytest.mark.asyncio
async def test_cash_receipt_voucher_settles_invoice(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    ar_account = await _account_by_subtype(client, headers, "ACCOUNTS_RECEIVABLE")
    cash_account = await _account_by_subtype(client, headers, "CASH")
    invoice = await _posted_invoice(client, headers)
    total = Decimal(str(invoice["grand_total"]))
    created = await client.post(
        "/api/v1/vouchers",
        headers=headers,
        json={
            "voucher_type": "CASH_RECEIPT",
            "payment_account_id": cash_account,
            "total_amount": str(total),
            "currency_id": invoice["currency_id"],
            "party_type": "CUSTOMER",
            "party_id": invoice["customer_id"],
            "payment_method": "CASH",
            "lines": [
                {
                    "account_id": ar_account,
                    "amount": str(total),
                    "party_type": "CUSTOMER",
                    "party_id": invoice["customer_id"],
                }
            ],
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
    voucher = created.json()["data"]
    posted = await client.post(
        f"/api/v1/vouchers/{voucher['id']}/post",
        headers=_idempotent(headers, voucher["version"]),
    )
    assert posted.status_code == 200, posted.text
    invoice_after = await client.get(f"/api/v1/sales-invoices/{invoice['id']}", headers=headers)
    assert Decimal(invoice_after.json()["data"]["balance_due"]) == Decimal("0")


@pytest.mark.asyncio
async def test_ar_line_without_party_rejected(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    ar_account = await _account_by_subtype(client, headers, "ACCOUNTS_RECEIVABLE")
    cash_account = await _account_by_subtype(client, headers, "CASH")
    created = await client.post(
        "/api/v1/vouchers",
        headers=headers,
        json={
            "voucher_type": "CASH_RECEIPT",
            "payment_account_id": cash_account,
            "total_amount": "100",
            "lines": [{"account_id": ar_account, "amount": "100"}],
        },
    )
    assert created.status_code == 422, created.text


@pytest.mark.asyncio
async def test_contra_voucher_rejected(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    cash_account = await _account_by_subtype(client, headers, "CASH")
    bank_account = await _account_by_subtype(client, headers, "BANK")
    created = await client.post(
        "/api/v1/vouchers",
        headers=headers,
        json={
            "voucher_type": "CONTRA",
            "payment_account_id": cash_account,
            "counter_account_id": bank_account,
            "total_amount": "250",
            "payment_method": "CASH",
        },
    )
    assert created.status_code == 422, created.text


@pytest.mark.asyncio
async def test_list_vouchers(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    empty = await client.get("/api/v1/vouchers", headers=headers)
    assert empty.status_code == 200, empty.text
    assert empty.json()["data"] == []
    cash_account = await _account_by_subtype(client, headers, "CASH")
    created = await client.post(
        "/api/v1/vouchers",
        headers=headers,
        json={
            "voucher_type": "CASH_RECEIPT",
            "payment_account_id": cash_account,
            "total_amount": "100",
            "lines": [],
        },
    )
    assert created.status_code == 422
    await _draft_cash_payment(client, headers)
    listed = await client.get("/api/v1/vouchers", headers=headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["meta"]["total"] == 1
    assert len(body["data"]) == 1
    assert body["data"][0]["voucher_type"] == "CASH_PAYMENT"


@pytest.mark.asyncio
async def test_day_book_endpoint(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    from datetime import date

    today = date.today().isoformat()
    response = await client.get(
        f"/api/v1/reports/day-book?from={today}&to={today}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["book_kind"] == "all"
    assert "sections" in body


@pytest.mark.asyncio
async def test_delete_draft_voucher(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    voucher = await _draft_cash_payment(client, headers, amount="75")
    assert "delete" in voucher["available_actions"]
    deleted = await client.delete(
        f"/api/v1/vouchers/{voucher['id']}",
        headers={**headers, "If-Match": str(voucher["version"])},
    )
    assert deleted.status_code == 200, deleted.text
    missing = await client.get(f"/api/v1/vouchers/{voucher['id']}", headers=headers)
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_journal_voucher_via_vouchers_endpoint(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    cash_account = await _account_by_subtype(client, headers, "CASH")
    revenue = await _counter_account(client, headers)
    created = await client.post(
        "/api/v1/vouchers",
        headers=headers,
        json={
            "voucher_type": "JOURNAL",
            "narration": "Standing accrual",
            "lines": [
                {"account_id": cash_account, "debit": "80", "credit": "0"},
                {"account_id": revenue, "debit": "0", "credit": "80"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    voucher = created.json()["data"]
    assert voucher["voucher_type"] == "JOURNAL"
    posted = await client.post(
        f"/api/v1/vouchers/{voucher['id']}/post",
        headers=_idempotent(headers, voucher["version"]),
    )
    assert posted.status_code == 200, posted.text
    journal = await client.get(
        f"/api/v1/vouchers/{voucher['id']}",
        headers=headers,
    )
    assert journal.status_code == 200, journal.text
    assert journal.json()["data"]["journal_entry_id"] is not None


@pytest.mark.asyncio
async def test_general_purchase_voucher_dr_cr_grid(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    expense = await _counter_account(client, headers)
    ap_account = await _account_by_subtype(client, headers, "ACCOUNTS_PAYABLE")
    created = await client.post(
        "/api/v1/vouchers",
        headers=headers,
        json={
            "voucher_type": "GENERAL_PURCHASE",
            "external_reference": "IMP-2026-001",
            "narration": "Import charges",
            "lines": [
                {"account_id": expense, "debit": "120", "credit": "0"},
                {"account_id": ap_account, "debit": "0", "credit": "120"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    voucher = created.json()["data"]
    assert voucher["voucher_type"] == "GENERAL_PURCHASE"
    assert voucher["external_reference"] == "IMP-2026-001"


@pytest.mark.asyncio
async def test_general_purchase_post_splits_vat_from_account_default_tax(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    expense = await _counter_account(client, headers)
    taxes = await client.get("/api/v1/taxes", headers=headers)
    assert taxes.status_code == 200, taxes.text
    tax_rows = taxes.json()["data"]
    assert tax_rows, "expected seeded tax"
    tax_id = tax_rows[0]["id"]
    patched = await client.patch(
        f"/api/v1/accounts/{expense}",
        headers=headers,
        json={"default_tax_id": tax_id},
    )
    assert patched.status_code == 200, patched.text
    ap_account = await _account_by_subtype(client, headers, "ACCOUNTS_PAYABLE")
    gross = Decimal("115")
    created = await client.post(
        "/api/v1/vouchers",
        headers=headers,
        json={
            "voucher_type": "GENERAL_PURCHASE",
            "narration": "GP with VAT",
            "lines": [
                {"account_id": expense, "debit": str(gross), "credit": "0"},
                {"account_id": ap_account, "debit": "0", "credit": str(gross)},
            ],
        },
    )
    assert created.status_code == 201, created.text
    voucher = created.json()["data"]
    posted = await client.post(
        f"/api/v1/vouchers/{voucher['id']}/post",
        headers=_idempotent(headers, voucher["version"]),
    )
    assert posted.status_code == 200, posted.text
    journal_id = posted.json()["data"]["journal_entry_id"]
    assert journal_id is not None
    journal = await client.get(f"/api/v1/journals/{journal_id}", headers=headers)
    assert journal.status_code == 200, journal.text
    lines = journal.json()["data"]["lines"]
    assert len(lines) >= 3


@pytest.mark.asyncio
async def test_voucher_print_includes_amount_in_words(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    voucher = await _draft_cash_payment(client, headers, amount="105")
    printed = await client.get(
        f"/api/v1/vouchers/{voucher['id']}/print",
        headers=headers,
    )
    assert printed.status_code == 200, printed.text
    body = printed.json()["data"]
    assert body["template_kind"] == "voucher"
    assert body["amount_in_words"] is not None
    assert len(body["journal_lines"]) >= 1


@pytest.mark.asyncio
async def test_bank_receipt_future_cheque_creates_pdc_linkage(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    today = await _enable_books(client, headers)
    bank = await _bank_account(client, headers)
    invoice = await _posted_invoice(client, headers)
    total = Decimal(str(invoice["grand_total"]))
    voucher_date = date.fromisoformat(today)
    cheque_date = (voucher_date + timedelta(days=30)).isoformat()
    ar_account = await _account_by_subtype(client, headers, "ACCOUNTS_RECEIVABLE")
    created = await client.post(
        "/api/v1/vouchers",
        headers=headers,
        json={
            "voucher_type": "BANK_RECEIPT",
            "voucher_date": today,
            "payment_account_id": bank["account_id"],
            "total_amount": str(total),
            "currency_id": invoice["currency_id"],
            "party_type": "CUSTOMER",
            "party_id": invoice["customer_id"],
            "payment_method": "CHEQUE",
            "cheque_number": "PDC-BRV-1",
            "cheque_date": cheque_date,
            "lines": [
                {
                    "account_id": ar_account,
                    "amount": str(total),
                    "party_type": "CUSTOMER",
                    "party_id": invoice["customer_id"],
                }
            ],
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
    voucher = created.json()["data"]
    posted = await client.post(
        f"/api/v1/vouchers/{voucher['id']}/post",
        headers=_idempotent(headers, voucher["version"]),
    )
    assert posted.status_code == 200, posted.text
    cheques = await client.get(
        "/api/v1/cheques",
        headers=headers,
        params={"party_id": invoice["customer_id"]},
    )
    assert cheques.status_code == 200, cheques.text
    rows = [row for row in cheques.json()["data"] if row["cheque_number"] == "PDC-BRV-1"]
    assert len(rows) == 1
    assert rows[0]["cheque_date"] == cheque_date
    assert rows[0]["voucher_id"] == voucher["id"]
    assert rows[0]["status"] == "DRAFT"


@pytest.mark.asyncio
async def test_voucher_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    await _enable_books(client, headers_a)
    await _enable_books(client, headers_b)
    voucher = await _draft_cash_payment(client, headers_a, amount="50")
    voucher_id = voucher["id"]
    foreign = await client.get(f"/api/v1/vouchers/{voucher_id}", headers=headers_b)
    assert foreign.status_code == 404

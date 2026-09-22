"""Phase 8 — bank accounts, reconciliation and cheques."""

from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.api.erp.customer_payments.test_routes import (
    _enable_books,
    _idempotent,
    _post_receipt,
    _posted_invoice,
)
from tests.conftest import login_headers, provision_admin


async def _bank_gl_account(client: AsyncClient, headers: dict[str, str]) -> str:
    listed = await client.get("/api/v1/accounts", headers=headers)
    assert listed.status_code == 200, listed.text
    for row in listed.json()["data"]:
        if row.get("account_subtype") == "BANK" and not row.get("is_group"):
            return row["id"]
    raise AssertionError("BANK account not found")


async def _base_currency(client: AsyncClient, headers: dict[str, str]) -> str:
    listed = await client.get("/api/v1/currencies", headers=headers)
    assert listed.status_code == 200, listed.text
    for row in listed.json()["data"]:
        if row.get("is_base"):
            return row["id"]
    raise AssertionError("base currency not found")


async def _bank_account(client: AsyncClient, headers: dict[str, str]) -> dict[str, object]:
    account_id = await _bank_gl_account(client, headers)
    currency_id = await _base_currency(client, headers)
    created = await client.post(
        "/api/v1/bank-accounts",
        headers=headers,
        json={
            "account_id": account_id,
            "account_name": "Operating Account",
            "bank_name": "Test Bank",
            "currency_id": currency_id,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]


@pytest.mark.asyncio
async def test_bank_account_crud(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    bank = await _bank_account(client, headers)
    fetched = await client.get(f"/api/v1/bank-accounts/{bank['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["data"]["bank_name"] == "Test Bank"


@pytest.mark.asyncio
async def test_bank_statement_import_and_match(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    bank = await _bank_account(client, headers)
    created = await client.post(
        "/api/v1/bank-reconciliation",
        headers=headers,
        json={
            "bank_account_id": bank["id"],
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "opening_balance": "0",
            "closing_balance": "1000",
            "lines": [
                {
                    "line_date": "2026-01-15",
                    "description": "Deposit",
                    "reference": "DEP001",
                    "debit": "0",
                    "credit": "1000",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    statement = created.json()["data"]
    assert len(statement["lines"]) == 1
    book = await client.get(
        f"/api/v1/bank-reconciliation/{statement['id']}/book-entries",
        headers=headers,
    )
    assert book.status_code == 200
    summary = await client.get(
        f"/api/v1/bank-reconciliation/{statement['id']}/reconciliation-statement",
        headers=headers,
    )
    assert summary.status_code == 200
    assert summary.json()["data"]["statement_balance"] == "1000.0000"


@pytest.mark.asyncio
async def test_inbound_cheque_issue_clear_and_bounce(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    bank = await _bank_account(client, headers)
    invoice = await _posted_invoice(client, headers)
    total = Decimal(str(invoice["grand_total"]))
    created = await client.post(
        "/api/v1/cheques",
        headers=headers,
        json={
            "cheque_number": "CHQ-1001",
            "direction": "INBOUND",
            "cheque_date": invoice["document_date"],
            "amount": str(total),
            "currency_id": invoice["currency_id"],
            "party_type": "CUSTOMER",
            "party_id": invoice["customer_id"],
            "bank_account_id": bank["id"],
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
    cheque = created.json()["data"]
    issued = await client.post(
        f"/api/v1/cheques/{cheque['id']}/issue",
        headers=_idempotent(headers, cheque["version"]),
    )
    assert issued.status_code == 200, issued.text
    cheque = issued.json()["data"]
    invoice_after = await client.get(f"/api/v1/sales-invoices/{invoice['id']}", headers=headers)
    assert invoice_after.json()["data"]["payment_status"] == "PAID"
    cleared = await client.post(
        f"/api/v1/cheques/{cheque['id']}/clear",
        headers=_idempotent(headers, cheque["version"]),
    )
    assert cleared.status_code == 200, cleared.text
    cheque = cleared.json()["data"]
    bounced = await client.post(
        f"/api/v1/cheques/{cheque['id']}/bounce",
        headers=_idempotent(headers, cheque["version"]),
        json={"reason": "Insufficient funds", "version": cheque["version"]},
    )
    assert bounced.status_code == 200, bounced.text
    bounced_cheque = bounced.json()["data"]
    assert bounced_cheque["reversal_journal_entry_id"] is not None
    assert bounced_cheque["clearing_reversal_journal_entry_id"] is not None
    assert len(bounced_cheque["allocations"]) == 1
    assert bounced_cheque["allocations"][0]["reversed_at"] is not None
    invoice_restored = await client.get(f"/api/v1/sales-invoices/{invoice['id']}", headers=headers)
    assert invoice_restored.json()["data"]["payment_status"] != "PAID"


@pytest.mark.asyncio
async def test_bank_statement_exclude_and_reconcile(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    bank = await _bank_account(client, headers)
    created = await client.post(
        "/api/v1/bank-reconciliation",
        headers=headers,
        json={
            "bank_account_id": bank["id"],
            "period_start": "2026-02-01",
            "period_end": "2026-02-28",
            "opening_balance": "0",
            "closing_balance": "500",
            "lines": [
                {
                    "line_date": "2026-02-10",
                    "description": "Unknown fee",
                    "reference": "FEE1",
                    "debit": "500",
                    "credit": "0",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    statement = created.json()["data"]
    line_id = statement["lines"][0]["id"]
    excluded = await client.post(
        f"/api/v1/bank-reconciliation/{statement['id']}/exclude",
        headers=headers,
        json={"statement_line_id": line_id, "version": statement["version"]},
    )
    assert excluded.status_code == 200, excluded.text
    statement = excluded.json()["data"]
    reconciled = await client.post(
        f"/api/v1/bank-reconciliation/{statement['id']}/reconcile",
        headers=_idempotent(headers, statement["version"]),
    )
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["data"]["status"] == "RECONCILED"


@pytest.mark.asyncio
async def test_reconcile_allows_unpresented_book_entries(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    today = await _enable_books(client, headers)
    bank = await _bank_account(client, headers)
    invoice = await _posted_invoice(client, headers)
    await _post_receipt(
        client,
        headers,
        {
            "customer_id": invoice["customer_id"],
            "payment_date": today,
            "currency_id": invoice["currency_id"],
            "amount_received": str(invoice["grand_total"]),
            "payment_account_id": bank["account_id"],
            "payment_method": "CHEQUE",
            "allocations": [
                {
                    "item_type": "SALES_INVOICE",
                    "item_id": invoice["id"],
                    "amount": str(invoice["grand_total"]),
                }
            ],
        },
    )
    created = await client.post(
        "/api/v1/bank-reconciliation",
        headers=headers,
        json={
            "bank_account_id": bank["id"],
            "period_start": today,
            "period_end": today,
            "opening_balance": "0",
            "closing_balance": "0",
            "lines": [
                {
                    "line_date": today,
                    "description": "Bank-only fee",
                    "reference": "FEE2",
                    "debit": "10",
                    "credit": "0",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    statement = created.json()["data"]
    line_id = statement["lines"][0]["id"]
    excluded = await client.post(
        f"/api/v1/bank-reconciliation/{statement['id']}/exclude",
        headers=headers,
        json={"statement_line_id": line_id, "version": statement["version"]},
    )
    assert excluded.status_code == 200, excluded.text
    statement = excluded.json()["data"]
    book = await client.get(
        f"/api/v1/bank-reconciliation/{statement['id']}/book-entries",
        headers=headers,
    )
    assert book.status_code == 200, book.text
    assert any(not row["is_matched"] for row in book.json()["data"])
    reconciled = await client.post(
        f"/api/v1/bank-reconciliation/{statement['id']}/reconcile",
        headers=_idempotent(headers, statement["version"]),
    )
    assert reconciled.status_code == 200, reconciled.text


@pytest.mark.asyncio
async def test_banking_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    bank = await _bank_account(client, headers_a)
    cross = await client.get(f"/api/v1/bank-accounts/{bank['id']}", headers=headers_b)
    assert cross.status_code == 404

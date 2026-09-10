"""API tests for trial balance, general ledger, and account statements."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.sales_orders.test_routes import _create_customer
from tests.api.erp.sales_orders.test_routes import _create_order as _create_sales_order
from tests.api.inventory_management.delivery_notes.test_routes import _receive_stock
from tests.conftest import login_headers, provision_admin


def _if_match(
    headers: dict[str, str], version: object, *, key: str | None = None
) -> dict[str, str]:
    extra = {**headers, "If-Match": str(version)}
    if key is not None:
        extra["Idempotency-Key"] = key
    return extra


async def _accounts(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    assert roles.status_code == 200, roles.text
    return {item["role"]: item["account_id"] for item in roles.json()["data"]}


@pytest.mark.asyncio
async def test_trial_balance_and_general_ledger_drill_through(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "narration": "Cash to bank",
            "lines": [
                {"account_id": accounts["BANK"], "debit": "40.0000", "credit": "0"},
                {"account_id": accounts["CASH_ON_HAND"], "debit": "0", "credit": "40.0000"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    posted = await client.post(
        f"/api/v1/journals/{row['id']}/post",
        headers=_if_match(headers, row["version"], key=uuid4().hex),
    )
    assert posted.status_code == 200, posted.text
    body = posted.json()["data"]
    entry_date = body["entry_date"]
    tb = await client.get(
        "/api/v1/reports/trial-balance",
        headers=headers,
        params={"from": entry_date, "to": entry_date},
    )
    assert tb.status_code == 200, tb.text
    trial = tb.json()["data"]
    assert trial["is_balanced"] is True
    assert trial["total_closing_debit"] == trial["total_closing_credit"]
    gl = await client.get(
        "/api/v1/reports/general-ledger",
        headers=headers,
        params={"account_id": accounts["BANK"], "from": entry_date, "to": entry_date},
    )
    assert gl.status_code == 200, gl.text
    lines = gl.json()["data"]["lines"]
    assert len(lines) == 1
    assert lines[0]["journal_entry_id"] == body["id"]
    assert lines[0]["document_number"] == body["document_number"]


@pytest.mark.asyncio
async def test_account_statement_includes_party_open_item(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    customer = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "name": "Statement customer",
            "code": f"C-{uuid4().hex[:8]}",
            "tax_treatment": "UNREGISTERED",
        },
    )
    assert customer.status_code == 201, customer.text
    customer_id = customer.json()["data"]["id"]
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "lines": [
                {
                    "account_id": accounts["ACCOUNTS_RECEIVABLE"],
                    "debit": "12.0000",
                    "credit": "0",
                    "party_type": "CUSTOMER",
                    "party_id": customer_id,
                    "due_date": "2026-12-01",
                    "external_reference": "INV-OPEN-2",
                },
                {"account_id": accounts["SALES_REVENUE"], "debit": "0", "credit": "12.0000"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    posted = await client.post(
        f"/api/v1/journals/{row['id']}/post",
        headers=_if_match(headers, row["version"], key=uuid4().hex),
    )
    assert posted.status_code == 200, posted.text
    entry_date = posted.json()["data"]["entry_date"]
    statement = await client.get(
        "/api/v1/reports/account-statement",
        headers=headers,
        params={
            "party_type": "CUSTOMER",
            "party_id": customer_id,
            "from": entry_date,
            "to": entry_date,
        },
    )
    assert statement.status_code == 200, statement.text
    data = statement.json()["data"]
    assert data["closing_balance"] == "12.0000"
    assert data["lines"][0]["external_reference"] == "INV-OPEN-2"
    assert data["lines"][0]["journal_entry_id"] == posted.json()["data"]["id"]


@pytest.mark.asyncio
async def test_export_and_cogs_pending_tax_reports(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    today = datetime.now(UTC).date().isoformat()
    updated = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"books_start_date": today},
    )
    assert updated.status_code == 200, updated.text
    ctx = await _receive_stock(client, headers, quantity="2")
    product_id = str(ctx["product_id"])
    customer_id = await _create_customer(client, headers, tax_treatment="EXPORT", trn=None)
    created = await _create_sales_order(
        client, headers, customer_id=customer_id, product_id=product_id, quantity="2"
    )
    assert created["status_code"] == 201, created["text"]
    confirmed = await client.post(
        f"/api/v1/sales-orders/{created['body']['data']['id']}/confirm",
        headers=_if_match(headers, created["body"]["data"]["version"]),
    )
    assert confirmed.status_code == 200, confirmed.text
    order = confirmed.json()["data"]
    invoice_created = await client.post(
        "/api/v1/sales-invoices/from-sales-order",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"sales_order_id": order["id"]},
    )
    assert invoice_created.status_code == 201, invoice_created.text
    invoice = invoice_created.json()["data"]
    assert invoice["is_export"] is True
    posted = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/post",
        headers=_if_match(headers, invoice["version"], key=uuid4().hex),
    )
    assert posted.status_code == 200, posted.text
    data = posted.json()["data"]
    assert data["export_evidence_ok"] is False
    assert data["cogs_status"] == "PENDING"

    exceptions = await client.get(
        "/api/v1/reports/export-evidence-exceptions", headers=headers
    )
    assert exceptions.status_code == 200, exceptions.text
    exception_rows = exceptions.json()["data"]["lines"]
    assert len(exception_rows) == 1
    assert exception_rows[0]["sales_invoice_id"] == data["id"]
    assert exception_rows[0]["window_days"] == 90
    assert exception_rows[0]["overdue"] is False

    pending = await client.get("/api/v1/reports/invoiced-not-dispatched", headers=headers)
    assert pending.status_code == 200, pending.text
    pending_rows = pending.json()["data"]["lines"]
    assert len(pending_rows) == 1
    assert pending_rows[0]["sales_invoice_id"] == data["id"]
    assert pending_rows[0]["cogs_status"] == "PENDING"

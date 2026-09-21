"""Sales invoice write-off API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.quotation.test_routes import _create_customer, _seeded_ids
from tests.api.erp.sales_orders.test_routes import _create_product
from tests.conftest import login_headers, provision_admin


def _idempotent(headers: dict[str, str], version: object) -> dict[str, str]:
    return {**headers, "If-Match": str(version), "Idempotency-Key": uuid4().hex}


async def _posted_invoice(client: AsyncClient, headers: dict[str, str]) -> dict[str, object]:
    today = datetime.now(UTC).date().isoformat()
    updated = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"books_start_date": today},
    )
    assert updated.status_code == 200, updated.text
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
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


@pytest.mark.asyncio
async def test_partial_write_off_reduces_balance_and_posts_bad_debt(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    invoice = await _posted_invoice(client, headers)
    balance = Decimal(invoice["balance_due"])
    amount = (balance / 2).quantize(Decimal("0.0001"))
    write_off_date = datetime.now(UTC).date().isoformat()
    written = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/write-off",
        headers=_idempotent(headers, invoice["version"]),
        json={
            "amount": str(amount),
            "write_off_date": write_off_date,
            "reason": "Partial bad debt",
            "version": invoice["version"],
        },
    )
    assert written.status_code == 200, written.text
    body = written.json()
    data = body["data"]
    assert Decimal(data["amount_written_off"]) == amount
    assert Decimal(data["balance_due"]) == balance - amount
    assert "write_off_id" in body["meta"]
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    mapped = {item["role"]: item["account_id"] for item in roles.json()["data"]}
    assert "BAD_DEBT_EXPENSE" in mapped
    journals = await client.get("/api/v1/journals", headers=headers)
    assert journals.status_code == 200, journals.text
    write_off_journal = next(
        entry
        for entry in journals.json()["data"]
        if entry["source_type"] == "sales_invoice_write_off"
    )
    detail = await client.get(f"/api/v1/journals/{write_off_journal['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    by_account = {line["account_id"]: line for line in detail.json()["data"]["lines"]}
    assert Decimal(by_account[mapped["BAD_DEBT_EXPENSE"]]["debit"]) == amount
    assert Decimal(by_account[mapped["ACCOUNTS_RECEIVABLE"]]["credit"]) == amount


@pytest.mark.asyncio
async def test_write_off_refuses_amount_over_balance(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    invoice = await _posted_invoice(client, headers)
    over = Decimal(invoice["balance_due"]) + Decimal("1")
    response = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/write-off",
        headers=_idempotent(headers, invoice["version"]),
        json={
            "amount": str(over),
            "write_off_date": datetime.now(UTC).date().isoformat(),
            "version": invoice["version"],
        },
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_write_off_refuses_locked_period(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    invoice = await _posted_invoice(client, headers)
    lock_date = datetime.now(UTC).date().isoformat()
    locked = await client.patch(
        "/api/v1/period-lock",
        headers=headers,
        json={"hard_lock_date": lock_date, "reason": "Close month"},
    )
    assert locked.status_code == 200, locked.text
    response = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/write-off",
        headers=_idempotent(headers, invoice["version"]),
        json={
            "amount": invoice["balance_due"],
            "write_off_date": datetime.now(UTC).date().isoformat(),
            "version": invoice["version"],
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "PERIOD_LOCKED"


@pytest.mark.asyncio
async def test_reverse_write_off_restores_balance(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    invoice = await _posted_invoice(client, headers)
    write_off_date = datetime.now(UTC).date().isoformat()
    written = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/write-off",
        headers=_idempotent(headers, invoice["version"]),
        json={
            "amount": invoice["balance_due"],
            "write_off_date": write_off_date,
            "version": invoice["version"],
        },
    )
    assert written.status_code == 200, written.text
    payload = written.json()
    write_off_id = payload["meta"]["write_off_id"]
    invoice = payload["data"]
    assert Decimal(invoice["balance_due"]) == Decimal("0")
    reversed_resp = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/write-off/reverse",
        headers=_idempotent(headers, invoice["version"]),
        json={
            "write_off_id": write_off_id,
            "reversal_date": write_off_date,
            "version": invoice["version"],
        },
    )
    assert reversed_resp.status_code == 200, reversed_resp.text
    restored = reversed_resp.json()["data"]
    assert Decimal(restored["amount_written_off"]) == Decimal("0")
    assert Decimal(restored["balance_due"]) > Decimal("0")

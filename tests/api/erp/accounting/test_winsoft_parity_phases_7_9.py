"""Winsoft parity phases 7–9: print, PDC register, projection, credit hold."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.accounting.test_banking import _bank_account, _enable_books, _posted_invoice
from tests.api.erp.sales_orders.test_routes import _create_customer, _create_order, _create_product, _seeded_ids
from tests.conftest import login_headers, provision_admin


def _if_match(headers: dict[str, str], version: object) -> dict[str, str]:
    return {**headers, "If-Match": str(version)}


@pytest.mark.asyncio
async def test_pdc_register_lists_issued_cheque(client: AsyncClient) -> None:
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
            "cheque_number": "PDC-REG-1",
            "direction": "INBOUND",
            "cheque_date": invoice["document_date"],
            "due_date": "2026-12-20",
            "amount": str(total),
            "currency_id": invoice["currency_id"],
            "party_type": "CUSTOMER",
            "party_id": invoice["customer_id"],
            "bank_account_id": bank["id"],
        },
    )
    assert created.status_code == 201, created.text
    cheque = created.json()["data"]
    issued = await client.post(
        f"/api/v1/cheques/{cheque['id']}/issue",
        headers={**headers, "If-Match": str(cheque["version"]), "Idempotency-Key": uuid4().hex},
    )
    assert issued.status_code == 200, issued.text
    report = await client.get(
        "/api/v1/reports/pdc-register",
        headers=headers,
        params={"due_date_from": "2026-12-01", "due_date_to": "2026-12-31"},
    )
    assert report.status_code == 200, report.text
    lines = report.json()["data"]["lines"]
    assert any(line["cheque_number"] == "PDC-REG-1" for line in lines)
    assert Decimal(report.json()["data"]["total_inbound"]) >= total


@pytest.mark.asyncio
async def test_bank_balance_projection_includes_pdc(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    bank = await _bank_account(client, headers)
    projection = await client.get(
        f"/api/v1/bank-accounts/{bank['id']}/balance-projection",
        headers=headers,
        params={"as_of": "2026-01-01", "horizon_days": 90},
    )
    assert projection.status_code == 200, projection.text
    body = projection.json()["data"]
    assert body["bank_account_id"] == bank["id"]
    assert body["lines"][0]["kind"] == "book"


@pytest.mark.asyncio
async def test_cheque_print_includes_amount_in_words(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    bank = await _bank_account(client, headers)
    invoice = await _posted_invoice(client, headers)
    created = await client.post(
        "/api/v1/cheques",
        headers=headers,
        json={
            "cheque_number": "PRINT-1",
            "direction": "INBOUND",
            "cheque_date": invoice["document_date"],
            "amount": str(invoice["grand_total"]),
            "currency_id": invoice["currency_id"],
            "party_type": "CUSTOMER",
            "party_id": invoice["customer_id"],
            "bank_account_id": bank["id"],
        },
    )
    assert created.status_code == 201, created.text
    cheque_id = created.json()["data"]["id"]
    printed = await client.get(f"/api/v1/cheques/{cheque_id}/print", headers=headers)
    assert printed.status_code == 200, printed.text
    body = printed.json()["data"]
    assert body["template_kind"] == "cheque"
    assert body["amount_in_words"] is not None


@pytest.mark.asyncio
async def test_credit_hold_blocks_sales_order_confirm(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    held = await client.patch(
        f"/api/v1/customers/{customer_id}",
        headers=headers,
        json={"credit_hold": True},
    )
    assert held.status_code == 200, held.text
    product_id = await _create_product(client, headers, ids)
    created = await _create_order(client, headers, customer_id=customer_id, product_id=product_id)
    assert created["status_code"] == 201, created["text"]
    order = created["body"]["data"]
    confirmed = await client.post(
        f"/api/v1/sales-orders/{order['id']}/confirm",
        headers=_if_match(headers, order["version"]),
    )
    assert confirmed.status_code == 409, confirmed.text
    assert confirmed.json()["error"]["code"] == "CREDIT_HOLD"


@pytest.mark.asyncio
async def test_batch_deposit_cheques(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    bank = await _bank_account(client, headers)
    invoice = await _posted_invoice(client, headers)
    created = await client.post(
        "/api/v1/cheques",
        headers=headers,
        json={
            "cheque_number": "BATCH-1",
            "direction": "INBOUND",
            "cheque_date": invoice["document_date"],
            "amount": str(invoice["grand_total"]),
            "currency_id": invoice["currency_id"],
            "party_type": "CUSTOMER",
            "party_id": invoice["customer_id"],
            "bank_account_id": bank["id"],
        },
    )
    assert created.status_code == 201, created.text
    cheque = created.json()["data"]
    issued = await client.post(
        f"/api/v1/cheques/{cheque['id']}/issue",
        headers={**headers, "If-Match": str(cheque["version"]), "Idempotency-Key": uuid4().hex},
    )
    assert issued.status_code == 200, issued.text
    issued_cheque = issued.json()["data"]
    deposited = await client.post(
        "/api/v1/cheques/batch-deposit",
        headers=headers,
        json={"cheques": [{"id": issued_cheque["id"], "version": issued_cheque["version"]}]},
    )
    assert deposited.status_code == 200, deposited.text
    rows = deposited.json()["data"]
    assert len(rows) == 1
    assert rows[0]["status"] == "DEPOSITED"


@pytest.mark.asyncio
async def test_gl_integrity_scan_endpoint(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    response = await client.get("/api/v1/utilities/gl-integrity", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["ok"] is True
    assert body["issue_count"] == 0
    assert body["issues"] == []


@pytest.mark.asyncio
async def test_overdue_days_threshold_blocks_sales_order_confirm(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    invoice = await _posted_invoice(client, headers)
    updated = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"overdue_days_threshold": 0},
    )
    assert updated.status_code == 200, updated.text
    ids = await _seeded_ids(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_order(
        client,
        headers,
        customer_id=str(invoice["customer_id"]),
        product_id=product_id,
    )
    assert created["status_code"] == 201, created["text"]
    order = created["body"]["data"]
    confirmed = await client.post(
        f"/api/v1/sales-orders/{order['id']}/confirm",
        headers=_if_match(headers, order["version"]),
    )
    assert confirmed.status_code == 409, confirmed.text
    assert confirmed.json()["error"]["code"] == "CREDIT_OVERDUE"

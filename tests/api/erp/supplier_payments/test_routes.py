"""Supplier payments: bill settlement, FX, and void guards."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.purchase_orders.test_routes import (
    _create_order,
    _create_product,
    _create_supplier,
)
from tests.api.erp.purchase_orders.test_routes import _if_match as _po_if_match
from tests.api.erp.purchase_orders.test_routes import _seeded_ids as _po_seeded_ids
from tests.api.erp.quotation.test_routes import _currency_id
from tests.conftest import login_headers, provision_admin


def _idempotent(headers: dict[str, str], version: object) -> dict[str, str]:
    return {**headers, "If-Match": str(version), "Idempotency-Key": uuid4().hex}


async def _enable_books(client: AsyncClient, headers: dict[str, str]) -> None:
    today = datetime.now(UTC).date().isoformat()
    updated = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"books_start_date": today},
    )
    assert updated.status_code == 200, updated.text


async def _accounts(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    assert roles.status_code == 200, roles.text
    return {item["role"]: item["account_id"] for item in roles.json()["data"]}


async def _posted_expense_bill(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    supplier_id: str,
    rate: str = "100.0000",
    currency_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "supplier_id": supplier_id,
        "bill_type": "EXPENSE",
        "lines": [
            {
                "line_type": "EXPENSE",
                "description": "Ocean freight",
                "quantity": "1",
                "rate": rate,
                "expense_category": "FREIGHT",
            }
        ],
    }
    if currency_id is not None:
        payload["currency_id"] = currency_id
    created = await client.post("/api/v1/purchase-invoices", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    bill = created.json()["data"]
    posted = await client.post(
        f"/api/v1/purchase-invoices/{bill['id']}/post",
        headers=_idempotent(headers, bill["version"]),
    )
    assert posted.status_code == 200, posted.text
    return posted.json()["data"]


@pytest.mark.asyncio
async def test_pay_expense_bill_and_block_void(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    supplier_id = await _create_supplier(client, headers)
    bill = await _posted_expense_bill(client, headers, supplier_id=supplier_id)
    total = Decimal(str(bill["grand_total"]))
    created = await client.post(
        "/api/v1/supplier-payments",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "amount_paid": str(total),
            "payment_account_id": accounts["BANK"],
            "payment_method": "TT",
            "bank_charges": "2.0000",
            "allocations": [
                {
                    "item_type": "PURCHASE_INVOICE",
                    "item_id": bill["id"],
                    "amount": str(total),
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    posted = await client.post(
        f"/api/v1/supplier-payments/{created.json()['data']['id']}/post",
        headers=_idempotent(headers, created.json()["data"]["version"]),
    )
    assert posted.status_code == 200, posted.text
    fetched = await client.get(f"/api/v1/purchase-invoices/{bill['id']}", headers=headers)
    body = fetched.json()["data"]
    assert body["payment_status"] == "PAID"
    assert Decimal(body["balance_due"]) == Decimal("0")
    voided = await client.post(
        f"/api/v1/purchase-invoices/{bill['id']}/cancel",
        headers=_idempotent(headers, body["version"]),
    )
    assert voided.status_code == 409, voided.text
    journal = await client.get(
        f"/api/v1/supplier-payments/{posted.json()['data']['id']}/journal",
        headers=headers,
    )
    lines = journal.json()["data"]["lines"]
    charges = next(line for line in lines if line["account_id"] == accounts["BANK_CHARGES"])
    assert Decimal(charges["debit"]) == Decimal("2.0000")


@pytest.mark.asyncio
async def test_cny_bill_paid_later_books_fx(client: AsyncClient) -> None:
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
    supplier = await client.post(
        "/api/v1/suppliers",
        headers=headers,
        json={
            "name": "Shenzhen mill",
            "code": f"S-{uuid4().hex[:8]}",
            "tax_treatment": "UNREGISTERED",
            "currency_id": cny_id,
            "shipping_address": {
                "address_line_1": "Factory",
                "city": "Shenzhen",
                "state": "Guangdong",
                "country_code": "CN",
                "country": "China",
            },
            "billing_address": {
                "address_line_1": "Accounts",
                "city": "Shenzhen",
                "state": "Guangdong",
                "country_code": "CN",
                "country": "China",
            },
        },
    )
    assert supplier.status_code == 201, supplier.text
    supplier_id = supplier.json()["data"]["id"]
    bill = await _posted_expense_bill(
        client, headers, supplier_id=supplier_id, rate="100.0000", currency_id=cny_id
    )
    updated = await client.put(
        "/api/v1/exchange-rates",
        headers=headers,
        json={"currency_id": cny_id, "rate_to_base": "0.5500"},
    )
    assert updated.status_code == 200, updated.text
    created = await client.post(
        "/api/v1/supplier-payments",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "amount_paid": str(bill["grand_total"]),
            "currency_id": cny_id,
            "payment_account_id": accounts["BANK"],
            "payment_method": "TT",
            "allocations": [
                {
                    "item_type": "PURCHASE_INVOICE",
                    "item_id": bill["id"],
                    "amount": str(bill["grand_total"]),
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    posted = await client.post(
        f"/api/v1/supplier-payments/{created.json()['data']['id']}/post",
        headers=_idempotent(headers, created.json()["data"]["version"]),
    )
    assert posted.status_code == 200, posted.text
    journal = await client.get(
        f"/api/v1/supplier-payments/{posted.json()['data']['id']}/journal",
        headers=headers,
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


@pytest.mark.asyncio
async def test_tt_advance_auto_settles_bill_from_purchase_order(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    ids = await _po_seeded_ids(client, headers)
    supplier_id = await _create_supplier(client, headers, tax_treatment="UNREGISTERED", trn=None)
    product_id = await _create_product(client, headers, ids)
    created_po = await _create_order(
        client, headers, supplier_id=supplier_id, product_id=product_id
    )
    assert created_po["status_code"] == 201, created_po["text"]
    order = created_po["body"]["data"]
    issued = await client.post(
        f"/api/v1/purchase-orders/{order['id']}/issue",
        headers=_po_if_match(headers, order["version"]),
    )
    assert issued.status_code == 200, issued.text
    advance = Decimal("50.0000")
    created = await client.post(
        "/api/v1/supplier-payments",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "amount_paid": str(advance),
            "payment_account_id": accounts["BANK"],
            "payment_method": "TT",
            "purchase_order_id": order["id"],
        },
    )
    assert created.status_code == 201, created.text
    posted_pay = await client.post(
        f"/api/v1/supplier-payments/{created.json()['data']['id']}/post",
        headers=_idempotent(headers, created.json()["data"]["version"]),
    )
    assert posted_pay.status_code == 200, posted_pay.text
    assert Decimal(posted_pay.json()["data"]["amount_unapplied"]) == advance

    created_bill = await client.post(
        "/api/v1/purchase-invoices",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "purchase_order_id": order["id"],
            "bill_type": "EXPENSE",
            "lines": [
                {
                    "line_type": "EXPENSE",
                    "description": "Ocean freight",
                    "quantity": "1",
                    "rate": "100.0000",
                    "expense_category": "FREIGHT",
                }
            ],
        },
    )
    assert created_bill.status_code == 201, created_bill.text
    posted_bill = await client.post(
        f"/api/v1/purchase-invoices/{created_bill.json()['data']['id']}/post",
        headers=_idempotent(headers, created_bill.json()["data"]["version"]),
    )
    assert posted_bill.status_code == 200, posted_bill.text
    body = posted_bill.json()["data"]
    assert Decimal(body["amount_paid"]) == advance
    assert Decimal(body["balance_due"]) == Decimal(str(body["grand_total"])) - advance
    assert body["payment_status"] == "PARTIALLY_PAID"


@pytest.mark.asyncio
async def test_opening_ap_collection(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    today = datetime.now(UTC).date()
    supplier_id = await _create_supplier(client, headers, tax_treatment="UNREGISTERED", trn=None)
    committed = await client.post(
        "/api/v1/opening-balances/commit",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={
            "books_start_date": today.isoformat(),
            "gl_lines": [],
            "ar_items": [],
            "ap_items": [
                {
                    "party_id": supplier_id,
                    "amount": "90.0000",
                    "due_date": today.isoformat(),
                    "external_reference": "OB-AP-1",
                }
            ],
            "stock_lines": [],
        },
    )
    assert committed.status_code == 200, committed.text
    items = await client.get(f"/api/v1/suppliers/{supplier_id}/open-items", headers=headers)
    assert items.status_code == 200, items.text
    opening = next(row for row in items.json()["data"] if row["item_type"] == "OPENING_AP")
    created = await client.post(
        "/api/v1/supplier-payments",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "amount_paid": "90.0000",
            "payment_account_id": accounts["BANK"],
            "allocations": [
                {
                    "item_type": "OPENING_AP",
                    "item_id": opening["document_id"],
                    "amount": "90.0000",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    posted = await client.post(
        f"/api/v1/supplier-payments/{created.json()['data']['id']}/post",
        headers=_idempotent(headers, created.json()["data"]["version"]),
    )
    assert posted.status_code == 200, posted.text
    assert Decimal(posted.json()["data"]["amount_unapplied"]) == Decimal("0")
    remaining = await client.get(f"/api/v1/suppliers/{supplier_id}/open-items", headers=headers)
    assert remaining.json()["data"] == []

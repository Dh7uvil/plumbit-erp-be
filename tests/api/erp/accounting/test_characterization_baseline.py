"""Characterization baseline for posting, FX, GRN costing, and payment allocation.

These tests lock current correct behaviour before multi-currency and accounting refactors.
Do not loosen assertions when fixing unrelated defects — update only when behaviour intentionally
changes and the product owner accepts the new journal shape.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.customer_payments.test_routes import (
    _enable_books as _enable_books_payment,
)
from tests.api.erp.landed_costs.test_routes import _post_expense_bill
from tests.api.erp.purchase_invoices.test_routes import _enable_books
from tests.api.erp.purchase_orders.test_routes import (
    _create_product as _create_purchase_product,
)
from tests.api.erp.purchase_orders.test_routes import (
    _create_supplier,
    _if_match,
)
from tests.api.erp.quotation.test_routes import (
    _create_customer,
    _create_product,
    _currency_id,
    _seeded_ids,
)
from tests.api.inventory_management.goods_receipts.test_routes import (
    _create_from_po,
    _post_grn,
)
from tests.conftest import login_headers, provision_admin


def _idempotent(headers: dict[str, str], version: object) -> dict[str, str]:
    return {**headers, "If-Match": str(version), "Idempotency-Key": uuid4().hex}


async def _system_roles(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    assert roles.status_code == 200, roles.text
    return {item["role"]: item["account_id"] for item in roles.json()["data"]}


def _assert_journal_balanced(journal: dict[str, object]) -> None:
    lines = journal["lines"]
    assert isinstance(lines, list)
    debit = sum(Decimal(str(line["debit"])) for line in lines)
    credit = sum(Decimal(str(line["credit"])) for line in lines)
    debit_base = sum(Decimal(str(line["debit_base"])) for line in lines)
    credit_base = sum(Decimal(str(line["credit_base"])) for line in lines)
    assert debit == credit
    assert debit_base == credit_base
    assert debit_base > Decimal("0")


@pytest.mark.asyncio
async def test_baseline_sales_invoice_post_journal_in_document_and_base_currency(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    usd_id = await _currency_id(client, headers, "USD")
    saved = await client.put(
        "/api/v1/exchange-rates",
        headers=headers,
        json={"currency_id": usd_id, "rate_to_base": "3.672500"},
    )
    assert saved.status_code == 200, saved.text
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers, currency_id=usd_id)
    product_id = await _create_product(client, headers, ids, selling_rate="100.0000")
    created = await client.post(
        "/api/v1/sales-invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "currency_id": usd_id,
            "lines": [{"product_id": product_id, "quantity": "1"}],
        },
    )
    assert created.status_code == 201, created.text
    invoice = created.json()["data"]
    assert Decimal(invoice["exchange_rate"]) == Decimal("3.672500")
    assert Decimal(invoice["grand_total"]) == Decimal("105.0000")
    assert Decimal(invoice["base_amount"]) == Decimal("385.6125")
    posted = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/post",
        headers=_idempotent(headers, invoice["version"]),
    )
    assert posted.status_code == 200, posted.text
    journal = await client.get(
        f"/api/v1/sales-invoices/{invoice['id']}/journal", headers=headers
    )
    assert journal.status_code == 200, journal.text
    body = journal.json()["data"]
    _assert_journal_balanced(body)
    assert body["currency_id"] == usd_id
    assert Decimal(body["exchange_rate"]) == Decimal("3.672500")


@pytest.mark.asyncio
async def test_baseline_purchase_invoice_post_journal_in_document_and_base_currency(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    usd_id = await _currency_id(client, headers, "USD")
    fx_rate = Decimal("3.672500")
    saved = await client.put(
        "/api/v1/exchange-rates",
        headers=headers,
        json={"currency_id": usd_id, "rate_to_base": str(fx_rate)},
    )
    assert saved.status_code == 200, saved.text
    ids = await _seeded_ids(client, headers)
    supplier_id = await _create_supplier(client, headers)
    product_id = await _create_purchase_product(
        client, headers, ids, track_inventory=True, purchase_rate="50.0000"
    )
    po = await client.post(
        "/api/v1/purchase-orders",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "currency_id": usd_id,
            "lines": [{"product_id": product_id, "quantity": "2", "rate": "50.0000"}],
        },
    )
    assert po.status_code == 201, po.text
    issued = await client.post(
        f"/api/v1/purchase-orders/{po.json()['data']['id']}/issue",
        headers=_if_match(headers, po.json()["data"]["version"]),
    )
    assert issued.status_code == 200, issued.text
    receipt = await _create_from_po(client, headers, issued.json()["data"]["id"])
    assert receipt["status_code"] == 201, receipt["text"]
    posted_grn = await _post_grn(
        client, headers, receipt["body"]["data"]["id"], receipt["body"]["data"]["version"]
    )
    assert posted_grn.status_code == 200, posted_grn.text
    grn = posted_grn.json()["data"]
    goods = await client.post(
        "/api/v1/purchase-invoices/from-goods-receipt",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"goods_receipt_id": grn["id"]},
    )
    assert goods.status_code == 201, goods.text
    bill = goods.json()["data"]
    assert Decimal(bill["exchange_rate"]) == fx_rate
    posted = await client.post(
        f"/api/v1/purchase-invoices/{bill['id']}/post",
        headers=_idempotent(headers, bill["version"]),
    )
    assert posted.status_code == 200, posted.text
    journal = await client.get(
        f"/api/v1/purchase-invoices/{bill['id']}/journal", headers=headers
    )
    assert journal.status_code == 200, journal.text
    body = journal.json()["data"]
    _assert_journal_balanced(body)
    roles = await _system_roles(client, headers)
    by_account = {line["account_id"]: line for line in body["lines"]}
    assert roles["GOODS_RECEIVED_NOT_INVOICED"] in by_account
    assert body["currency_id"] == usd_id
    assert Decimal(body["exchange_rate"]) == fx_rate


@pytest.mark.asyncio
async def test_baseline_grn_fifo_layer_and_landed_cost_clears_parked_account(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    usd_id = await _currency_id(client, headers, "USD")
    fx_rate = Decimal("2.0000")
    saved = await client.put(
        "/api/v1/exchange-rates",
        headers=headers,
        json={"currency_id": usd_id, "rate_to_base": str(fx_rate)},
    )
    assert saved.status_code == 200, saved.text
    ids = await _seeded_ids(client, headers)
    supplier_id = await _create_supplier(client, headers)
    product_id = await _create_purchase_product(
        client, headers, ids, track_inventory=True, purchase_rate="40.0000"
    )
    po = await client.post(
        "/api/v1/purchase-orders",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "currency_id": usd_id,
            "lines": [{"product_id": product_id, "quantity": "1", "rate": "40.0000"}],
        },
    )
    assert po.status_code == 201, po.text
    issued = await client.post(
        f"/api/v1/purchase-orders/{po.json()['data']['id']}/issue",
        headers=_if_match(headers, po.json()["data"]["version"]),
    )
    assert issued.status_code == 200, issued.text
    receipt = await _create_from_po(client, headers, issued.json()["data"]["id"])
    assert receipt["status_code"] == 201, receipt["text"]
    grn_row = receipt["body"]["data"]
    assert Decimal(grn_row["exchange_rate"]) == fx_rate
    posted_grn = await _post_grn(client, headers, grn_row["id"], grn_row["version"])
    assert posted_grn.status_code == 200, posted_grn.text
    grn = posted_grn.json()["data"]
    stock = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    row = stock.json()["data"][0]
    layers = await client.get(f"/api/v1/stock/{row['id']}/layers", headers=headers)
    expected_unit_cost = quantize_money(Decimal("40.0000") * fx_rate)
    assert Decimal(layers.json()["data"][0]["unit_cost"]) == expected_unit_cost

    freight = await _post_expense_bill(
        client, headers, supplier_id=supplier_id, grn_id=grn["id"], rate="20.0000"
    )
    lc_created = await client.post(
        "/api/v1/landed-costs",
        headers=headers,
        json={
            "allocation_method": "VALUE",
            "charges": [{"purchase_invoice_line_id": freight["lines"][0]["id"]}],
            "allocations": [{"goods_receipt_line_id": grn["lines"][0]["id"]}],
        },
    )
    assert lc_created.status_code == 201, lc_created.text
    lc = lc_created.json()["data"]
    lc_posted = await client.post(
        f"/api/v1/landed-costs/{lc['id']}/post",
        headers=_idempotent(headers, lc["version"]),
    )
    assert lc_posted.status_code == 200, lc_posted.text
    roles = await _system_roles(client, headers)
    lc_journal = await client.get(
        f"/api/v1/landed-costs/{lc['id']}/journal", headers=headers
    )
    assert lc_journal.status_code == 200, lc_journal.text
    by_account = {line["account_id"]: line for line in lc_journal.json()["data"]["lines"]}
    assert Decimal(by_account[roles["FREIGHT_IN"]]["credit"]) == Decimal("20.0000")
    assert Decimal(by_account[roles["INVENTORY"]]["debit"]) == Decimal("20.0000")


def quantize_money(value: Decimal) -> Decimal:
    from app.common.utils.currency import quantize_money as _q

    return _q(value)


@pytest.mark.asyncio
async def test_baseline_realized_fx_on_foreign_receipt_at_different_rate(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books_payment(client, headers)
    accounts = await _system_roles(client, headers)
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
    invoice_body = posted.json()["data"]
    await client.put(
        "/api/v1/exchange-rates",
        headers=headers,
        json={"currency_id": cny_id, "rate_to_base": "0.5500"},
    )
    receipt_created = await client.post(
        "/api/v1/customer-payments",
        headers=headers,
        json={
            "customer_id": customer_id,
            "amount_received": str(invoice_body["grand_total"]),
            "currency_id": cny_id,
            "payment_account_id": accounts["BANK"],
            "allocations": [
                {
                    "item_type": "SALES_INVOICE",
                    "item_id": invoice["id"],
                    "amount": str(invoice_body["grand_total"]),
                }
            ],
        },
    )
    assert receipt_created.status_code == 201, receipt_created.text
    row = receipt_created.json()["data"]
    posted_receipt = await client.post(
        f"/api/v1/customer-payments/{row['id']}/post",
        headers=_idempotent(headers, row["version"]),
    )
    assert posted_receipt.status_code == 200, posted_receipt.text
    journal = await client.get(
        f"/api/v1/customer-payments/{row['id']}/journal", headers=headers
    )
    fx_lines = [
        line
        for line in journal.json()["data"]["lines"]
        if line["account_id"] == accounts["FX_GAIN_LOSS"]
    ]
    assert fx_lines
    fx_amount = sum(Decimal(line["debit"]) - Decimal(line["credit"]) for line in fx_lines)
    assert fx_amount != Decimal("0")


@pytest.mark.asyncio
async def test_baseline_allocate_rejects_over_allocation_and_currency_mismatch(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books_payment(client, headers)
    accounts = await _system_roles(client, headers)
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
    total = Decimal(str(posted.json()["data"]["grand_total"]))

    over = await client.post(
        "/api/v1/customer-payments",
        headers=headers,
        json={
            "customer_id": customer_id,
            "currency_id": cny_id,
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
    assert over.status_code == 422, over.text
    assert over.json()["error"]["code"] == "PAYMENT_OVER_ALLOCATED"

    mismatch = await client.post(
        "/api/v1/customer-payments",
        headers=headers,
        json={
            "customer_id": customer_id,
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
    assert mismatch.status_code == 201, mismatch.text
    payment = mismatch.json()["data"]
    posted_payment = await client.post(
        f"/api/v1/customer-payments/{payment['id']}/post",
        headers=_idempotent(headers, payment["version"]),
    )
    assert posted_payment.status_code == 422, posted_payment.text
    mismatch_msg = "Payment currency must match the open item currency"
    assert posted_payment.json()["error"]["message"] == mismatch_msg

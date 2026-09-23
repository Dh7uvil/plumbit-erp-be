"""API tests for refunding unapplied debit note balances."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.customer_payments.test_routes import _accounts, _enable_books, _idempotent
from tests.api.erp.purchase_orders.test_routes import (
    _create_order,
    _create_product,
    _create_supplier,
    _seeded_ids,
)
from tests.api.inventory_management.goods_receipts.test_routes import _create_from_po, _post_grn
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_refund_debit_note_from_purchase_return_posts_bank_inflow(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    ids = await _seeded_ids(client, headers)
    supplier_id = await _create_supplier(client, headers)
    product_id = await _create_product(client, headers, ids)

    billed_order = await _create_order(
        client, headers, supplier_id=supplier_id, product_id=product_id, quantity="4"
    )
    billed_issue = await client.post(
        f"/api/v1/purchase-orders/{billed_order['body']['data']['id']}/issue",
        headers=_idempotent(headers, billed_order["body"]["data"]["version"]),
    )
    assert billed_issue.status_code == 200, billed_issue.text
    billed_grn = await _create_from_po(client, headers, billed_issue.json()["data"]["id"])
    billed_posted = await _post_grn(
        client,
        headers,
        billed_grn["body"]["data"]["id"],
        billed_grn["body"]["data"]["version"],
    )
    assert billed_posted.status_code == 200, billed_posted.text
    goods = await client.post(
        "/api/v1/purchase-invoices/from-goods-receipt",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"goods_receipt_id": billed_posted.json()["data"]["id"]},
    )
    assert goods.status_code == 201, goods.text
    posted_pi = await client.post(
        f"/api/v1/purchase-invoices/{goods.json()['data']['id']}/post",
        headers=_idempotent(headers, goods.json()["data"]["version"]),
    )
    assert posted_pi.status_code == 200, posted_pi.text

    return_order = await _create_order(
        client, headers, supplier_id=supplier_id, product_id=product_id, quantity="4"
    )
    return_issue = await client.post(
        f"/api/v1/purchase-orders/{return_order['body']['data']['id']}/issue",
        headers=_idempotent(headers, return_order["body"]["data"]["version"]),
    )
    assert return_issue.status_code == 200, return_issue.text
    return_grn = await _create_from_po(client, headers, return_issue.json()["data"]["id"])
    return_posted = await _post_grn(
        client,
        headers,
        return_grn["body"]["data"]["id"],
        return_grn["body"]["data"]["version"],
    )
    assert return_posted.status_code == 200, return_posted.text
    receipt = return_posted.json()["data"]
    grn_line = receipt["lines"][0]

    created_return = await client.post(
        "/api/v1/purchase-returns",
        headers=headers,
        json={
            "goods_receipt_id": receipt["id"],
            "reason_code": "WRONG_ITEM",
            "lines": [
                {
                    "goods_receipt_line_id": grn_line["id"],
                    "product_id": grn_line["product_id"],
                    "quantity": "2",
                    "disposition": "RETURN_TO_SUPPLIER",
                }
            ],
        },
    )
    assert created_return.status_code == 201, created_return.text
    posted_return = await client.post(
        f"/api/v1/purchase-returns/{created_return.json()['data']['id']}/post",
        headers=_idempotent(headers, created_return.json()["data"]["version"]),
    )
    assert posted_return.status_code == 200, posted_return.text

    created_note = await client.post(
        "/api/v1/debit-notes/from-purchase-return",
        headers={**headers, "Idempotency-Key": "debit-from-pr"},
        json={
            "purchase_return_id": posted_return.json()["data"]["id"],
            "reason_code": "PRICE_ADJUSTMENT",
        },
    )
    assert created_note.status_code == 201, created_note.text
    note = created_note.json()["data"]
    assert note["purchase_invoice_id"] is None
    posted_note = await client.post(
        f"/api/v1/debit-notes/{note['id']}/post",
        headers=_idempotent(headers, note["version"]),
    )
    assert posted_note.status_code == 200, posted_note.text
    posted_row = posted_note.json()["data"]
    unapplied = Decimal(str(posted_row["amount_unapplied"]))
    assert unapplied > Decimal("0")

    refunded = await client.post(
        f"/api/v1/debit-notes/{posted_row['id']}/refund",
        headers=_idempotent(headers, posted_row["version"]),
        json={"payment_account_id": accounts["BANK"]},
    )
    assert refunded.status_code == 200, refunded.text
    data = refunded.json()["data"]
    assert data["refund_journal_entry_id"]
    assert Decimal(data["amount_unapplied"]) == Decimal("0")
    assert Decimal(data["amount_refunded"]) == unapplied

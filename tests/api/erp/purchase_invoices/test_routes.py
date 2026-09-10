"""API tests for purchase invoices: goods, freight, and import VAT against one GRN."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.inventory_management.goods_receipts.test_routes import (
    _create_from_po,
    _idempotent,
    _issue_tracked_po,
    _post_grn,
)
from tests.conftest import login_headers, provision_admin


async def _enable_books(client: AsyncClient, headers: dict[str, str]) -> None:
    today = datetime.now(UTC).date().isoformat()
    updated = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"books_start_date": today},
    )
    assert updated.status_code == 200, updated.text


@pytest.mark.asyncio
async def test_three_bills_against_one_grn_reconcile(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    ctx = await _issue_tracked_po(client, headers, quantity="4")
    created = await _create_from_po(client, headers, ctx["order"]["id"])
    posted_grn = await _post_grn(
        client, headers, created["body"]["data"]["id"], created["body"]["data"]["version"]
    )
    assert posted_grn.status_code == 200, posted_grn.text
    grn = posted_grn.json()["data"]
    supplier_id = str(ctx["supplier_id"])

    goods = await client.post(
        "/api/v1/purchase-invoices/from-goods-receipt",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"goods_receipt_id": grn["id"]},
    )
    assert goods.status_code == 201, goods.text
    goods_posted = await client.post(
        f"/api/v1/purchase-invoices/{goods.json()['data']['id']}/post",
        headers=_idempotent(headers, goods.json()["data"]["version"]),
    )
    assert goods_posted.status_code == 200, goods_posted.text
    goods_data = goods_posted.json()["data"]
    assert goods_data["bill_type"] == "GOODS"
    assert Decimal(goods_data["lines"][0]["grn_unit_cost"]) > Decimal("0")

    freight = await client.post(
        "/api/v1/purchase-invoices",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "bill_type": "EXPENSE",
            "goods_receipt_id": grn["id"],
            "lines": [
                {
                    "line_type": "EXPENSE",
                    "description": "Ocean freight",
                    "quantity": "1",
                    "rate": "50.0000",
                    "expense_category": "FREIGHT",
                }
            ],
        },
    )
    assert freight.status_code == 201, freight.text
    freight_posted = await client.post(
        f"/api/v1/purchase-invoices/{freight.json()['data']['id']}/post",
        headers=_idempotent(headers, freight.json()["data"]["version"]),
    )
    assert freight_posted.status_code == 200, freight_posted.text

    import_vat = await client.post(
        "/api/v1/purchase-invoices",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "bill_type": "IMPORT",
            "goods_receipt_id": grn["id"],
            "lines": [
                {
                    "line_type": "EXPENSE",
                    "description": "Import VAT",
                    "quantity": "1",
                    "rate": "16.0000",
                    "expense_category": "CUSTOMS_DUTY",
                }
            ],
        },
    )
    assert import_vat.status_code == 201, import_vat.text
    assert import_vat.json()["data"]["is_reverse_charge"] is True
    import_posted = await client.post(
        f"/api/v1/purchase-invoices/{import_vat.json()['data']['id']}/post",
        headers=_idempotent(headers, import_vat.json()["data"]["version"]),
    )
    assert import_posted.status_code == 200, import_posted.text
    rcm = import_posted.json()["data"]
    assert Decimal(rcm["rcm_tax_amount"]) > Decimal("0")

    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    mapped = {item["role"]: item["account_id"] for item in roles.json()["data"]}
    goods_journal = await client.get(
        f"/api/v1/purchase-invoices/{goods_data['id']}/journal", headers=headers
    )
    assert goods_journal.status_code == 200, goods_journal.text
    goods_accounts = {line["account_id"] for line in goods_journal.json()["data"]["lines"]}
    assert mapped["GOODS_RECEIVED_NOT_INVOICED"] in goods_accounts
    assert mapped["ACCOUNTS_PAYABLE"] in goods_accounts

    freight_journal = await client.get(
        f"/api/v1/purchase-invoices/{freight_posted.json()['data']['id']}/journal",
        headers=headers,
    )
    freight_by_account = {
        line["account_id"]: line for line in freight_journal.json()["data"]["lines"]
    }
    assert Decimal(freight_by_account[mapped["FREIGHT_IN"]]["debit"]) == Decimal("50.0000")

    import_journal = await client.get(
        f"/api/v1/purchase-invoices/{rcm['id']}/journal", headers=headers
    )
    import_by_account = {
        line["account_id"]: line for line in import_journal.json()["data"]["lines"]
    }
    assert Decimal(import_by_account[mapped["VAT_RCM_INPUT"]]["debit"]) == Decimal(
        import_by_account[mapped["VAT_RCM_OUTPUT"]]["credit"]
    )

    po = await client.get(f"/api/v1/purchase-orders/{ctx['order']['id']}", headers=headers)
    assert po.json()["data"]["billing_status"] == "INVOICED"
    dn = await client.get(f"/api/v1/goods-receipts/{grn['id']}", headers=headers)
    assert Decimal(dn.json()["data"]["lines"][0]["qty_billed"]) == Decimal("4")

    history = await client.get(
        f"/api/v1/suppliers/{supplier_id}/purchase-history", headers=headers
    )
    assert history.status_code == 200, history.text
    assert Decimal(history.json()["data"][0]["billed_cost"]) == Decimal(
        goods_data["lines"][0]["amount"]
    )


@pytest.mark.asyncio
async def test_void_goods_bill_restores_qty_billed(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    ctx = await _issue_tracked_po(client, headers, quantity="2")
    created = await _create_from_po(client, headers, ctx["order"]["id"])
    posted_grn = await _post_grn(
        client, headers, created["body"]["data"]["id"], created["body"]["data"]["version"]
    )
    goods = await client.post(
        "/api/v1/purchase-invoices/from-goods-receipt",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"goods_receipt_id": posted_grn.json()["data"]["id"]},
    )
    posted = await client.post(
        f"/api/v1/purchase-invoices/{goods.json()['data']['id']}/post",
        headers=_idempotent(headers, goods.json()["data"]["version"]),
    )
    assert posted.status_code == 200, posted.text
    cancelled = await client.post(
        f"/api/v1/purchase-invoices/{goods.json()['data']['id']}/cancel",
        headers=_idempotent(headers, posted.json()["data"]["version"]),
        json={"reason": "Posted in error"},
    )
    assert cancelled.status_code == 200, cancelled.text
    po = await client.get(f"/api/v1/purchase-orders/{ctx['order']['id']}", headers=headers)
    assert po.json()["data"]["billing_status"] == "NOT_INVOICED"

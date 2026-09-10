"""API tests for debit notes: from posted PI, journal reverses AP."""

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
async def test_from_posted_bill_post_reverses_ap(client: AsyncClient) -> None:
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
    assert goods.status_code == 201, goods.text
    posted_pi = await client.post(
        f"/api/v1/purchase-invoices/{goods.json()['data']['id']}/post",
        headers=_idempotent(headers, goods.json()["data"]["version"]),
    )
    assert posted_pi.status_code == 200, posted_pi.text
    invoice = posted_pi.json()["data"]

    created_dn = await client.post(
        "/api/v1/debit-notes/from-purchase-invoice",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"purchase_invoice_id": invoice["id"]},
    )
    assert created_dn.status_code == 201, created_dn.text
    note = created_dn.json()["data"]
    assert note["status"] == "DRAFT"
    assert note["purchase_invoice_id"] == invoice["id"]

    posted = await client.post(
        f"/api/v1/debit-notes/{note['id']}/post",
        headers=_idempotent(headers, note["version"]),
    )
    assert posted.status_code == 200, posted.text
    data = posted.json()["data"]
    assert data["status"] == "POSTED"
    assert data["journal_entry_id"]
    assert Decimal(data["amount_applied"]) == Decimal(str(data["grand_total"]))

    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    mapped = {item["role"]: item["account_id"] for item in roles.json()["data"]}
    journal = await client.get(f"/api/v1/debit-notes/{data['id']}/journal", headers=headers)
    assert journal.status_code == 200, journal.text
    by_account = {line["account_id"]: line for line in journal.json()["data"]["lines"]}
    ap = by_account[mapped["ACCOUNTS_PAYABLE"]]
    assert Decimal(ap["debit"]) == Decimal(str(invoice["grand_total"]))
    assert mapped["GOODS_RECEIVED_NOT_INVOICED"] in by_account

    pi = await client.get(f"/api/v1/purchase-invoices/{invoice['id']}", headers=headers)
    pi_data = pi.json()["data"]
    assert Decimal(pi_data["amount_debited"]) == Decimal(str(data["grand_total"]))
    assert Decimal(pi_data["lines"][0]["qty_debited"]) == Decimal(
        str(pi_data["lines"][0]["quantity"])
    )

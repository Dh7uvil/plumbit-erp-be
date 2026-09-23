"""API tests for refunding unapplied credit note balances."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.api.erp.customer_payments.test_routes import (
    _accounts,
    _enable_books,
    _idempotent,
    _posted_invoice,
    _seeded_ids,
)
from tests.api.erp.sales_orders.test_routes import _create_product
from tests.conftest import login_headers, provision_admin


async def _seed_bank_balance(
    client: AsyncClient,
    headers: dict[str, str],
    accounts: dict[str, str],
    *,
    amount: str = "1000.0000",
) -> None:
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "narration": "Seed bank balance",
            "lines": [
                {"account_id": accounts["BANK"], "debit": amount, "credit": "0"},
                {"account_id": accounts["CASH_ON_HAND"], "debit": "0", "credit": amount},
            ],
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    posted = await client.post(
        f"/api/v1/journals/{row['id']}/post",
        headers=_idempotent(headers, row["version"]),
    )
    assert posted.status_code == 200, posted.text


@pytest.mark.asyncio
async def test_refund_standalone_credit_note_posts_bank_outflow(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    await _seed_bank_balance(client, headers, accounts)
    ids = await _seeded_ids(client, headers)
    invoice = await _posted_invoice(client, headers)
    created = await client.post(
        "/api/v1/credit-notes",
        headers=headers,
        json={
            "customer_id": invoice["customer_id"],
            "reason_code": "PRICE_ADJUSTMENT",
            "lines": [
                {
                    "product_id": await _create_product(client, headers, ids),
                    "quantity": "1",
                    "rate": "25.0000",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    note = created.json()["data"]
    posted = await client.post(
        f"/api/v1/credit-notes/{note['id']}/post",
        headers=_idempotent(headers, note["version"]),
    )
    assert posted.status_code == 200, posted.text
    posted_note = posted.json()["data"]
    unapplied = Decimal(str(posted_note["amount_unapplied"]))
    assert unapplied > Decimal("0")

    refunded = await client.post(
        f"/api/v1/credit-notes/{posted_note['id']}/refund",
        headers=_idempotent(headers, posted_note["version"]),
        json={"payment_account_id": accounts["BANK"]},
    )
    assert refunded.status_code == 200, refunded.text
    data = refunded.json()["data"]
    assert data["refund_journal_entry_id"]
    assert Decimal(data["amount_unapplied"]) == Decimal("0")
    assert Decimal(data["amount_refunded"]) == unapplied

    journal = await client.get(
        f"/api/v1/credit-notes/{data['id']}/journal", headers=headers
    )
    assert journal.status_code == 200, journal.text
    refund_journal = await client.get(
        f"/api/v1/journals/{data['refund_journal_entry_id']}", headers=headers
    )
    assert refund_journal.status_code == 200, refund_journal.text

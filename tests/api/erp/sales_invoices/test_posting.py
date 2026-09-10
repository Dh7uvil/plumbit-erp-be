"""Sales invoice posting journal shape."""

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


@pytest.mark.asyncio
async def test_round_off_and_shipping_post_to_dedicated_accounts(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
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
            "shipping_amount": "15.0000",
            "round_off_amount": "0.0500",
            "lines": [{"product_id": product_id, "quantity": "1"}],
        },
    )
    assert created.status_code == 201, created.text
    invoice = created.json()["data"]
    assert Decimal(invoice["shipping_amount"]) == Decimal("15.0000")
    assert Decimal(invoice["round_off_amount"]) == Decimal("0.0500")
    posted = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/post",
        headers=_idempotent(headers, invoice["version"]),
    )
    assert posted.status_code == 200, posted.text
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    mapped = {item["role"]: item["account_id"] for item in roles.json()["data"]}
    journal = await client.get(
        f"/api/v1/sales-invoices/{invoice['id']}/journal", headers=headers
    )
    assert journal.status_code == 200, journal.text
    by_account = {line["account_id"]: line for line in journal.json()["data"]["lines"]}
    assert Decimal(by_account[mapped["SHIPPING_INCOME"]]["credit"]) == Decimal("15.0000")
    assert Decimal(by_account[mapped["ROUND_OFF"]]["credit"]) == Decimal("0.0500")
    debit = sum(Decimal(line["debit"]) for line in journal.json()["data"]["lines"])
    credit = sum(Decimal(line["credit"]) for line in journal.json()["data"]["lines"])
    assert debit == credit

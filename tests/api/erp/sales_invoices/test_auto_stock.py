"""Auto stock (Update Stock) on sales invoice post."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.sales_orders.test_routes import _create_customer
from tests.api.inventory_management.delivery_notes.test_routes import (
    _idempotent,
    _receive_stock,
)
from tests.conftest import login_headers, provision_admin


async def _enable_books(client: AsyncClient, headers: dict[str, str]) -> None:
    from datetime import UTC, datetime

    today = datetime.now(UTC).date().isoformat()
    updated = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"books_start_date": today},
    )
    assert updated.status_code == 200, updated.text


@pytest.mark.asyncio
async def test_post_with_update_stock_creates_and_posts_delivery_note(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    ctx = await _receive_stock(client, headers, quantity="10")
    product_id = str(ctx["product_id"])
    customer_id = await _create_customer(client, headers, trn=f"200{uuid4().int % 10**12:012d}")
    created = await client.post(
        "/api/v1/sales-invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "auto_stock_document": True,
            "lines": [{"product_id": product_id, "quantity": "4"}],
        },
    )
    assert created.status_code == 201, created.text
    invoice = created.json()["data"]
    posted = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/post",
        headers=_idempotent(headers, invoice["version"]),
    )
    assert posted.status_code == 200, posted.text
    body = posted.json()["data"]
    assert Decimal(body["lines"][0]["qty_delivered"]) == Decimal("4")

    notes = await client.get(
        "/api/v1/delivery-notes",
        headers=headers,
        params={"page": 1, "page_size": 50},
    )
    assert notes.status_code == 200, notes.text
    linked = [
        row
        for row in notes.json()["data"]
        if row.get("source_sales_invoice_id") == invoice["id"]
    ]
    assert len(linked) == 1
    assert linked[0]["status"] == "POSTED"
    assert (linked[0].get("notes") or "").startswith("Auto stock")

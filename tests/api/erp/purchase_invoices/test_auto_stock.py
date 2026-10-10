"""Auto stock (Update Stock) on purchase invoice post."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.api.erp.purchase_invoices.test_routes import _enable_books
from tests.api.inventory_management.goods_receipts.test_routes import (
    _idempotent,
    _issue_tracked_po,
)
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_post_with_update_stock_creates_and_posts_goods_receipt(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    ctx = await _issue_tracked_po(client, headers, quantity="6")
    product_id = str(ctx["product_id"])
    supplier_id = str(ctx["supplier_id"])

    created = await client.post(
        "/api/v1/purchase-invoices",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "auto_stock_document": True,
            "lines": [{"product_id": product_id, "quantity": "3", "rate": "10"}],
        },
    )
    assert created.status_code == 201, created.text
    invoice = created.json()["data"]
    posted = await client.post(
        f"/api/v1/purchase-invoices/{invoice['id']}/post",
        headers=_idempotent(headers, invoice["version"]),
    )
    assert posted.status_code == 200, posted.text
    body = posted.json()["data"]
    assert Decimal(body["lines"][0]["qty_received"]) == Decimal("3")

    receipts = await client.get(
        "/api/v1/goods-receipts",
        headers=headers,
        params={"page": 1, "page_size": 50},
    )
    assert receipts.status_code == 200, receipts.text
    linked = [
        row
        for row in receipts.json()["data"]
        if row.get("source_purchase_invoice_id") == invoice["id"]
    ]
    assert len(linked) == 1
    assert linked[0]["status"] == "POSTED"
    assert (linked[0].get("notes") or "").startswith("Auto stock")

"""Billing queue and purchase cycle endpoints."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.api.inventory_management.goods_receipts.test_routes import (
    _create_from_po,
    _issue_tracked_po,
    _post_grn,
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
async def test_purchase_order_billing_queue_and_cycle(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    ctx = await _issue_tracked_po(client, headers, quantity="4")
    po_id = ctx["order"]["id"]

    queue = await client.get("/api/v1/purchase-orders/billing-queue", headers=headers)
    assert queue.status_code == 200, queue.text
    items = queue.json()["data"]
    assert any(item["id"] == po_id for item in items)
    po_item = next(item for item in items if item["id"] == po_id)
    assert Decimal(po_item["lines"][0]["qty_remaining"]) == Decimal("4")

    cycle = await client.get(f"/api/v1/purchase-orders/{po_id}/cycle", headers=headers)
    assert cycle.status_code == 200, cycle.text
    rows = cycle.json()["data"]["rows"]
    types = {row["document_type"] for row in rows if row.get("document_id")}
    assert "PURCHASE_ORDER" in types

    created = await _create_from_po(client, headers, po_id)
    posted_grn = await _post_grn(
        client, headers, created["body"]["data"]["id"], created["body"]["data"]["version"]
    )
    assert posted_grn.status_code == 200, posted_grn.text
    grn_id = posted_grn.json()["data"]["id"]

    grn_queue = await client.get("/api/v1/goods-receipts/billing-queue", headers=headers)
    assert grn_queue.status_code == 200, grn_queue.text
    grn_items = grn_queue.json()["data"]
    assert any(item["id"] == grn_id for item in grn_items)

    cycle_after = await client.get(f"/api/v1/purchase-orders/{po_id}/cycle", headers=headers)
    types_after = {
        row["document_type"] for row in cycle_after.json()["data"]["rows"] if row.get("document_id")
    }
    assert "GOODS_RECEIPT" in types_after


@pytest.mark.asyncio
async def test_billing_queue_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    await _enable_books(client, headers_a)
    ctx = await _issue_tracked_po(client, headers_a, quantity="2")

    tenant_b, email_b, password_b = await provision_admin()
    headers_b = await login_headers(client, tenant_b, email_b, password_b)

    foreign = await client.get(
        f"/api/v1/purchase-orders/{ctx['order']['id']}/cycle",
        headers=headers_b,
    )
    assert foreign.status_code == 404, foreign.text

    queue_b = await client.get("/api/v1/purchase-orders/billing-queue", headers=headers_b)
    assert queue_b.status_code == 200, queue_b.text
    assert all(item["id"] != ctx["order"]["id"] for item in queue_b.json()["data"])

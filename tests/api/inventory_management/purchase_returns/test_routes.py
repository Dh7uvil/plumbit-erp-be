"""API tests for purchase returns: consume GRN layers without AP posting."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.api.inventory_management.goods_receipts.test_routes import (
    _create_from_po,
    _idempotent,
    _issue_tracked_po,
    _post_grn,
)
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_partial_purchase_return_reduces_on_hand(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _issue_tracked_po(client, headers, quantity="6", requires_qc=False)
    created = await _create_from_po(client, headers, ctx["order"]["id"])
    posted = await _post_grn(
        client, headers, created["body"]["data"]["id"], created["body"]["data"]["version"]
    )
    receipt = posted.json()["data"]
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
    assert posted_return.json()["data"]["status"] == "POSTED"

    stock = await client.get(f"/api/v1/stock?product_id={ctx['product_id']}", headers=headers)
    row = stock.json()["data"][0]
    assert Decimal(row["qty_on_hand"]) == Decimal("4")

    overflow = await client.post(
        "/api/v1/purchase-returns",
        headers=headers,
        json={
            "goods_receipt_id": receipt["id"],
            "reason_code": "WRONG_ITEM",
            "lines": [
                {
                    "goods_receipt_line_id": grn_line["id"],
                    "quantity": "5",
                    "disposition": "RETURN_TO_SUPPLIER",
                }
            ],
        },
    )
    assert overflow.status_code == 422, overflow.text


@pytest.mark.asyncio
async def test_purchase_return_releases_grn_hold_and_stock_hold(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _issue_tracked_po(client, headers, quantity="4", requires_qc=True)
    created = await _create_from_po(client, headers, ctx["order"]["id"])
    posted = await _post_grn(
        client, headers, created["body"]["data"]["id"], created["body"]["data"]["version"]
    )
    inspections = await client.get(
        f"/api/v1/quality-inspections?goods_receipt_id={posted.json()['data']['id']}",
        headers=headers,
    )
    qi = inspections.json()["data"][0]
    updated = await client.patch(
        f"/api/v1/quality-inspections/{qi['id']}",
        headers=_idempotent(headers, qi["version"]),
        json={
            "version": qi["version"],
            "lines": [
                {
                    "goods_receipt_line_id": qi["lines"][0]["goods_receipt_line_id"],
                    "qty_inspected": "4",
                    "qty_accepted": "1",
                    "qty_rejected": "3",
                    "qty_rework": "0",
                    "disposition": "RETURN_TO_SUPPLIER",
                }
            ],
        },
    )
    assert updated.status_code == 200, updated.text
    approved = await client.post(
        f"/api/v1/quality-inspections/{qi['id']}/approve",
        headers=_idempotent(headers, updated.json()["data"]["version"]),
    )
    assert approved.status_code == 200, approved.text
    receipt = posted.json()["data"]
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

    receipt_after = await client.get(
        f"/api/v1/goods-receipts/{receipt['id']}",
        headers=headers,
    )
    line = receipt_after.json()["data"]["lines"][0]
    assert Decimal(line["qty_on_hold"]) == Decimal("1")
    assert Decimal(line["qty_returned"]) == Decimal("2")

    stock = await client.get(f"/api/v1/stock?product_id={ctx['product_id']}", headers=headers)
    row = stock.json()["data"][0]
    assert Decimal(row["qty_quality_hold"]) == Decimal("1")

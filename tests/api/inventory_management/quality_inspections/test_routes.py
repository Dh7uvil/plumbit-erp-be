"""API tests for quality inspection approve, scrap, and quantity rules."""

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
async def test_scrap_disposition_writes_off_held_qty(client: AsyncClient) -> None:
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
                    "disposition": "SCRAP",
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
    stock = await client.get(f"/api/v1/stock?product_id={ctx['product_id']}", headers=headers)
    row = stock.json()["data"][0]
    assert Decimal(row["qty_on_hand"]) == Decimal("1")
    assert Decimal(row["qty_quality_hold"]) == Decimal("0")
    assert Decimal(row["qty_available"]) == Decimal("1")
    receipt = await client.get(
        f"/api/v1/goods-receipts/{posted.json()['data']['id']}", headers=headers
    )
    assert receipt.json()["data"]["qc_status"] == "CLEARED"
    assert Decimal(receipt.json()["data"]["lines"][0]["qty_accepted"]) == Decimal("1")
    assert Decimal(receipt.json()["data"]["lines"][0]["qty_rejected"]) == Decimal("3")


@pytest.mark.asyncio
async def test_inspection_qty_mismatch_is_rejected(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _issue_tracked_po(client, headers, quantity="2", requires_qc=True)
    created = await _create_from_po(client, headers, ctx["order"]["id"])
    posted = await _post_grn(
        client, headers, created["body"]["data"]["id"], created["body"]["data"]["version"]
    )
    inspections = await client.get(
        f"/api/v1/quality-inspections?goods_receipt_id={posted.json()['data']['id']}",
        headers=headers,
    )
    qi = inspections.json()["data"][0]
    mismatch = await client.patch(
        f"/api/v1/quality-inspections/{qi['id']}",
        headers=_idempotent(headers, qi["version"]),
        json={
            "version": qi["version"],
            "lines": [
                {
                    "goods_receipt_line_id": qi["lines"][0]["goods_receipt_line_id"],
                    "qty_inspected": "2",
                    "qty_accepted": "2",
                    "qty_rejected": "1",
                    "qty_rework": "0",
                }
            ],
        },
    )
    assert mismatch.status_code == 422, mismatch.text
    assert mismatch.json()["error"]["code"] == "QUALITY_QTY_MISMATCH"


@pytest.mark.asyncio
async def test_cannot_inspect_more_than_remaining_hold(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _issue_tracked_po(client, headers, quantity="2", requires_qc=True)
    created = await _create_from_po(client, headers, ctx["order"]["id"])
    posted = await _post_grn(
        client, headers, created["body"]["data"]["id"], created["body"]["data"]["version"]
    )
    extra = await client.post(
        "/api/v1/quality-inspections",
        headers=headers,
        json={
            "goods_receipt_id": posted.json()["data"]["id"],
            "lines": [
                {
                    "goods_receipt_line_id": posted.json()["data"]["lines"][0]["id"],
                    "qty_inspected": "3",
                    "qty_accepted": "3",
                    "qty_rejected": "0",
                    "qty_rework": "0",
                }
            ],
        },
    )
    assert extra.status_code == 422, extra.text
    assert extra.json()["error"]["code"] == "QUALITY_QTY_MISMATCH"

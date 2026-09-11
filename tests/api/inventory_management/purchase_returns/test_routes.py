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

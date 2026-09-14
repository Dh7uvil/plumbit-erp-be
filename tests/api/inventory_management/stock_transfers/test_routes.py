"""API tests for stock transfers between warehouses."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.inventory_management.delivery_notes.test_routes import _receive_stock
from tests.api.inventory_management.stock.test_stock_routes import _create_warehouse
from tests.conftest import login_headers, provision_admin


def _idempotent(headers: dict[str, str], version: object) -> dict[str, str]:
    return {**headers, "If-Match": str(version), "Idempotency-Key": uuid4().hex}


@pytest.mark.asyncio
async def test_stock_transfer_moves_on_hand_between_warehouses(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _receive_stock(client, headers, quantity="10")
    product_id = str(ctx["product_id"])
    from_warehouse_id = str(ctx["warehouse_id"])
    to_warehouse_id = await _create_warehouse(client, headers)

    created = await client.post(
        "/api/v1/stock-transfers",
        headers=headers,
        json={
            "from_warehouse_id": from_warehouse_id,
            "to_warehouse_id": to_warehouse_id,
            "lines": [{"product_id": product_id, "quantity": "4"}],
        },
    )
    assert created.status_code == 201, created.text
    transfer = created.json()["data"]
    posted = await client.post(
        f"/api/v1/stock-transfers/{transfer['id']}/post",
        headers=_idempotent(headers, transfer["version"]),
    )
    assert posted.status_code == 200, posted.text

    stock = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    assert stock.status_code == 200, stock.text
    by_warehouse = {row["warehouse_id"]: row for row in stock.json()["data"]}
    assert Decimal(by_warehouse[from_warehouse_id]["qty_on_hand"]) == Decimal("6")
    assert Decimal(by_warehouse[to_warehouse_id]["qty_on_hand"]) == Decimal("4")

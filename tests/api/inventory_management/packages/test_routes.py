"""API tests for packages: packing metadata with no stock writes."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.api.erp.sales_orders.test_routes import _if_match
from tests.api.inventory_management.delivery_notes.test_routes import (
    _confirm_sales_order,
    _create_and_post_delivery_note,
    _receive_stock,
)
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_package_pack_and_attach_does_not_move_stock(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _receive_stock(client, headers, quantity="4")
    product_id = str(ctx["product_id"])
    order = await _confirm_sales_order(client, headers, product_id=product_id, quantity="4")
    packable = await client.get(
        f"/api/v1/sales-orders/{order['id']}/packable-lines", headers=headers
    )
    assert packable.status_code == 200, packable.text
    so_line_id = packable.json()["data"][0]["sales_order_line_id"]

    created = await client.post(
        "/api/v1/packages",
        headers=headers,
        json={
            "sales_order_id": order["id"],
            "package_number": "CTN-1",
            "lines": [{"sales_order_line_id": so_line_id, "quantity": "4"}],
        },
    )
    assert created.status_code == 201, created.text
    packed = await client.post(
        f"/api/v1/packages/{created.json()['data']['id']}/pack",
        headers=_if_match(headers, created.json()["data"]["version"]),
    )
    assert packed.status_code == 200, packed.text
    assert packed.json()["data"]["status"] == "PACKED"

    before = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    qty_before = Decimal(before.json()["data"][0]["qty_on_hand"])
    note = await _create_and_post_delivery_note(client, headers, order["id"])
    attached = await client.post(
        f"/api/v1/delivery-notes/{note['id']}/packages",
        headers=headers,
        json={"package_id": packed.json()["data"]["id"]},
    )
    assert attached.status_code == 200, attached.text
    assert attached.json()["data"]["delivery_note_id"] == note["id"]

    after = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    assert Decimal(after.json()["data"][0]["qty_on_hand"]) == qty_before - Decimal("4")

    overflow = await client.post(
        "/api/v1/packages",
        headers=headers,
        json={
            "sales_order_id": order["id"],
            "lines": [{"sales_order_line_id": so_line_id, "quantity": "1"}],
        },
    )
    assert overflow.status_code == 422, overflow.text

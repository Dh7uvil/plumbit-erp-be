"""API tests for shipments: logistics wrapper with no stock or ledger writes."""

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
async def test_shipment_groups_posted_notes_without_moving_stock(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _receive_stock(client, headers, quantity="2")
    product_id = str(ctx["product_id"])
    order = await _confirm_sales_order(client, headers, product_id=product_id, quantity="2")
    note = await _create_and_post_delivery_note(client, headers, order["id"])
    before = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    qty_before = Decimal(before.json()["data"][0]["qty_on_hand"])

    created = await client.post(
        "/api/v1/shipments",
        headers=headers,
        json={"shipment_type": "EXPORT", "transport_mode": "SEA"},
    )
    assert created.status_code == 201, created.text
    shipment = created.json()["data"]
    attached = await client.post(
        f"/api/v1/shipments/{shipment['id']}/delivery-notes",
        headers=headers,
        json={"delivery_note_ids": [note["id"]]},
    )
    assert attached.status_code == 200, attached.text

    dispatched = await client.post(
        f"/api/v1/shipments/{shipment['id']}/dispatch",
        headers=_if_match(headers, attached.json()["data"]["version"]),
    )
    assert dispatched.status_code == 200, dispatched.text
    assert dispatched.json()["data"]["status"] == "DISPATCHED"

    tracked = await client.patch(
        f"/api/v1/shipments/{shipment['id']}/tracking",
        headers=_if_match(headers, dispatched.json()["data"]["version"]),
        json={"eta": "2026-09-20", "carrier_name": "Maersk"},
    )
    assert tracked.status_code == 200, tracked.text
    assert tracked.json()["data"]["carrier_name"] == "Maersk"

    after = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    assert Decimal(after.json()["data"][0]["qty_on_hand"]) == qty_before

    blocked = await client.post(
        f"/api/v1/delivery-notes/{note['id']}/cancel",
        headers={
            **headers,
            "If-Match": str(note["version"]),
            "Idempotency-Key": "cancel-shipped",
        },
        json={"reason": "Already shipped"},
    )
    assert blocked.status_code == 409, blocked.text

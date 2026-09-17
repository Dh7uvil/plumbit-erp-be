"""API tests for shipments: logistics wrapper with no stock or ledger writes."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.api.erp.purchase_orders.test_routes import _create_supplier
from tests.api.erp.sales_orders.test_routes import _create_customer, _if_match
from tests.api.inventory_management.delivery_notes.test_routes import (
    _confirm_sales_order,
    _create_and_post_delivery_note,
    _receive_stock,
)
from tests.conftest import login_headers, provision_admin


async def _create_package(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    sales_order_id: str,
    so_line_id: str,
    quantity: str,
    gross_weight: str | None = None,
    net_weight: str | None = None,
    delivery_note_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "sales_order_id": sales_order_id,
        "lines": [{"sales_order_line_id": so_line_id, "quantity": quantity}],
    }
    if gross_weight is not None:
        payload["gross_weight"] = gross_weight
    if net_weight is not None:
        payload["net_weight"] = net_weight
    if delivery_note_id is not None:
        payload["delivery_note_id"] = delivery_note_id
    created = await client.post("/api/v1/packages", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    return created.json()["data"]


async def _packable_line_id(
    client: AsyncClient, headers: dict[str, str], sales_order_id: str
) -> str:
    packable = await client.get(
        f"/api/v1/sales-orders/{sales_order_id}/packable-lines", headers=headers
    )
    assert packable.status_code == 200, packable.text
    return str(packable.json()["data"][0]["sales_order_line_id"])


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


@pytest.mark.asyncio
async def test_dispatch_requires_a_delivery_note(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    created = await client.post(
        "/api/v1/shipments",
        headers=headers,
        json={"shipment_type": "DOMESTIC", "transport_mode": "ROAD"},
    )
    assert created.status_code == 201, created.text
    shipment = created.json()["data"]
    dispatched = await client.post(
        f"/api/v1/shipments/{shipment['id']}/dispatch",
        headers=_if_match(headers, shipment["version"]),
    )
    assert dispatched.status_code == 422, dispatched.text
    assert "delivery note" in dispatched.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_create_shipment_with_supplier_freight_forwarder(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    supplier_id = await _create_supplier(client, headers)
    created = await client.post(
        "/api/v1/shipments",
        headers=headers,
        json={
            "shipment_type": "EXPORT",
            "transport_mode": "SEA",
            "freight_forwarder_id": supplier_id,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["freight_forwarder_id"] == supplier_id
    assert created.json()["data"]["gross_weight"] is None
    assert created.json()["data"]["total_packages"] is None


@pytest.mark.asyncio
async def test_create_shipment_rejects_customer_freight_forwarder(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    customer_id = await _create_customer(client, headers)
    created = await client.post(
        "/api/v1/shipments",
        headers=headers,
        json={
            "shipment_type": "EXPORT",
            "transport_mode": "SEA",
            "freight_forwarder_id": customer_id,
        },
    )
    assert created.status_code == 422, created.text
    assert "freight forwarder" in created.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_create_shipment_rejects_inactive_freight_forwarder(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    supplier_id = await _create_supplier(client, headers)
    deactivated = await client.patch(
        f"/api/v1/suppliers/{supplier_id}",
        headers=headers,
        json={"is_active": False},
    )
    assert deactivated.status_code == 200, deactivated.text
    created = await client.post(
        "/api/v1/shipments",
        headers=headers,
        json={
            "shipment_type": "EXPORT",
            "transport_mode": "SEA",
            "freight_forwarder_id": supplier_id,
        },
    )
    assert created.status_code == 422, created.text
    assert "freight forwarder" in created.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_shipment_totals_roll_up_from_packages(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _receive_stock(client, headers, quantity="4")
    product_id = str(ctx["product_id"])
    order = await _confirm_sales_order(client, headers, product_id=product_id, quantity="4")
    so_line_id = await _packable_line_id(client, headers, order["id"])
    note = await _create_and_post_delivery_note(client, headers, order["id"])
    await _create_package(
        client,
        headers,
        sales_order_id=order["id"],
        so_line_id=so_line_id,
        quantity="2",
        gross_weight="10",
        net_weight="8",
        delivery_note_id=note["id"],
    )
    second = await _create_package(
        client,
        headers,
        sales_order_id=order["id"],
        so_line_id=so_line_id,
        quantity="2",
        gross_weight="6",
        net_weight="4",
        delivery_note_id=note["id"],
    )

    created = await client.post(
        "/api/v1/shipments",
        headers=headers,
        json={
            "shipment_type": "EXPORT",
            "transport_mode": "SEA",
            "gross_weight": "999",
            "total_packages": 50,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["gross_weight"] is None
    shipment = created.json()["data"]

    attached = await client.post(
        f"/api/v1/shipments/{shipment['id']}/delivery-notes",
        headers=headers,
        json={"delivery_note_ids": [note["id"]]},
    )
    assert attached.status_code == 200, attached.text
    data = attached.json()["data"]
    assert data["total_packages"] == 2
    assert Decimal(data["gross_weight"]) == Decimal("16")
    assert Decimal(data["net_weight"]) == Decimal("12")

    detached = await client.delete(
        f"/api/v1/shipments/{shipment['id']}/delivery-notes/{note['id']}",
        headers=headers,
    )
    assert detached.status_code == 200, detached.text
    assert detached.json()["data"]["total_packages"] is None
    assert detached.json()["data"]["gross_weight"] is None
    assert detached.json()["data"]["net_weight"] is None

    reattached = await client.post(
        f"/api/v1/shipments/{shipment['id']}/delivery-notes",
        headers=headers,
        json={"delivery_note_ids": [note["id"]]},
    )
    assert reattached.status_code == 200, reattached.text
    cancelled = await client.post(
        f"/api/v1/packages/{second['id']}/cancel",
        headers=_if_match(headers, second["version"]),
    )
    assert cancelled.status_code == 200, cancelled.text
    refreshed = await client.get(f"/api/v1/shipments/{shipment['id']}", headers=headers)
    assert refreshed.status_code == 200, refreshed.text
    totals = refreshed.json()["data"]
    assert totals["total_packages"] == 1
    assert Decimal(totals["gross_weight"]) == Decimal("10")
    assert Decimal(totals["net_weight"]) == Decimal("8")


@pytest.mark.asyncio
async def test_attaching_package_to_shipped_note_updates_totals(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _receive_stock(client, headers, quantity="2")
    product_id = str(ctx["product_id"])
    order = await _confirm_sales_order(client, headers, product_id=product_id, quantity="2")
    so_line_id = await _packable_line_id(client, headers, order["id"])
    note = await _create_and_post_delivery_note(client, headers, order["id"])
    created = await client.post(
        "/api/v1/shipments",
        headers=headers,
        json={"shipment_type": "DOMESTIC", "transport_mode": "ROAD"},
    )
    assert created.status_code == 201, created.text
    shipment = created.json()["data"]
    attached = await client.post(
        f"/api/v1/shipments/{shipment['id']}/delivery-notes",
        headers=headers,
        json={"delivery_note_ids": [note["id"]]},
    )
    assert attached.status_code == 200, attached.text
    assert attached.json()["data"]["total_packages"] == 0
    assert attached.json()["data"]["gross_weight"] is None

    pkg = await _create_package(
        client,
        headers,
        sales_order_id=order["id"],
        so_line_id=so_line_id,
        quantity="2",
        gross_weight="5.5",
        net_weight="4.25",
    )
    linked = await client.post(
        f"/api/v1/delivery-notes/{note['id']}/packages",
        headers=headers,
        json={"package_id": pkg["id"]},
    )
    assert linked.status_code == 200, linked.text
    refreshed = await client.get(f"/api/v1/shipments/{shipment['id']}", headers=headers)
    assert refreshed.status_code == 200, refreshed.text
    totals = refreshed.json()["data"]
    assert totals["total_packages"] == 1
    assert Decimal(totals["gross_weight"]) == Decimal("5.5")
    assert Decimal(totals["net_weight"]) == Decimal("4.25")

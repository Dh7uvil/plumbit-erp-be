"""API tests for goods receipts: PO receive, over-receipt, QC hold, and cancel."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.purchase_orders.test_routes import (
    _create_order,
    _create_product,
    _create_supplier,
    _if_match,
    _seeded_ids,
)
from tests.conftest import login_headers, provision_admin


async def _main_warehouse(client: AsyncClient, headers: dict[str, str]) -> str:
    warehouses = await client.get("/api/v1/warehouses?page_size=100", headers=headers)
    assert warehouses.status_code == 200, warehouses.text
    return next(item["id"] for item in warehouses.json()["data"] if item["code"] == "MAIN")


def _idempotent(
    headers: dict[str, str], version: object, *, key: str | None = None
) -> dict[str, str]:
    extra = {**headers, "If-Match": str(version), "Idempotency-Key": key or uuid4().hex}
    return extra


async def _issue_tracked_po(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    quantity: str = "10",
    requires_qc: bool = False,
    track_inventory: bool = True,
) -> dict[str, object]:
    ids = await _seeded_ids(client, headers)
    supplier_id = await _create_supplier(client, headers)
    product_id = await _create_product(
        client,
        headers,
        ids,
        track_inventory=track_inventory,
        requires_qc=requires_qc,
    )
    created = await _create_order(
        client, headers, supplier_id=supplier_id, product_id=product_id, quantity=quantity
    )
    issued = await client.post(
        f"/api/v1/purchase-orders/{created['body']['data']['id']}/issue",
        headers=_if_match(headers, created["body"]["data"]["version"]),
    )
    assert issued.status_code == 200, issued.text
    return {
        "order": issued.json()["data"],
        "product_id": product_id,
        "supplier_id": supplier_id,
        "warehouse_id": await _main_warehouse(client, headers),
    }


async def _create_from_po(
    client: AsyncClient, headers: dict[str, str], purchase_order_id: str
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/goods-receipts/from-purchase-order",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"purchase_order_id": purchase_order_id},
    )
    return {"status_code": response.status_code, "body": response.json(), "text": response.text}


async def _post_grn(
    client: AsyncClient, headers: dict[str, str], receipt_id: str, version: object
) -> object:
    return await client.post(
        f"/api/v1/goods-receipts/{receipt_id}/post",
        headers=_idempotent(headers, version),
    )


@pytest.mark.asyncio
async def test_partial_then_complete_receive_from_issued_po(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _issue_tracked_po(client, headers, quantity="10")
    order = ctx["order"]
    first = await _create_from_po(client, headers, order["id"])
    assert first["status_code"] == 201, first["text"]
    receipt = first["body"]["data"]
    patched = await client.patch(
        f"/api/v1/goods-receipts/{receipt['id']}",
        headers=_if_match(headers, receipt["version"]),
        json={
            "version": receipt["version"],
            "lines": [
                {
                    "purchase_order_line_id": receipt["lines"][0]["purchase_order_line_id"],
                    "product_id": receipt["lines"][0]["product_id"],
                    "quantity": "4",
                    "rate": receipt["lines"][0]["rate"],
                    "description": receipt["lines"][0]["description"],
                    "unit_id": receipt["lines"][0]["unit_id"],
                }
            ],
        },
    )
    assert patched.status_code == 200, patched.text
    posted = await _post_grn(client, headers, receipt["id"], patched.json()["data"]["version"])
    assert posted.status_code == 200, posted.text
    posted_data = posted.json()["data"]
    assert posted_data["status"] == "POSTED"
    assert posted_data["qc_status"] == "NOT_REQUIRED"

    po = await client.get(f"/api/v1/purchase-orders/{order['id']}", headers=headers)
    assert po.json()["data"]["receipt_status"] == "PARTIALLY_RECEIVED"
    stock = await client.get(f"/api/v1/stock?product_id={ctx['product_id']}", headers=headers)
    row = stock.json()["data"][0]
    assert Decimal(row["qty_on_hand"]) == Decimal("4")
    assert Decimal(row["qty_available"]) == Decimal("4")
    assert Decimal(row["qty_incoming"]) == Decimal("6")
    layers = await client.get(f"/api/v1/stock/{row['id']}/layers", headers=headers)
    assert Decimal(layers.json()["data"][0]["unit_cost"]) == Decimal("80.0000")

    second = await _create_from_po(client, headers, order["id"])
    assert second["status_code"] == 201, second["text"]
    assert Decimal(second["body"]["data"]["lines"][0]["quantity"]) == Decimal("6")
    posted_rest = await _post_grn(
        client, headers, second["body"]["data"]["id"], second["body"]["data"]["version"]
    )
    assert posted_rest.status_code == 200, posted_rest.text
    po_done = await client.get(f"/api/v1/purchase-orders/{order['id']}", headers=headers)
    assert po_done.json()["data"]["receipt_status"] == "RECEIVED"
    stock_done = await client.get(f"/api/v1/stock?product_id={ctx['product_id']}", headers=headers)
    done = stock_done.json()["data"][0]
    assert Decimal(done["qty_on_hand"]) == Decimal("10")
    assert Decimal(done["qty_incoming"]) == Decimal("0")


@pytest.mark.asyncio
async def test_over_receipt_is_blocked_when_tenant_disallows(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _issue_tracked_po(client, headers, quantity="2")
    created = await _create_from_po(client, headers, ctx["order"]["id"])
    receipt = created["body"]["data"]
    patched = await client.patch(
        f"/api/v1/goods-receipts/{receipt['id']}",
        headers=_if_match(headers, receipt["version"]),
        json={
            "version": receipt["version"],
            "lines": [
                {
                    "purchase_order_line_id": receipt["lines"][0]["purchase_order_line_id"],
                    "product_id": receipt["lines"][0]["product_id"],
                    "quantity": "3",
                    "rate": receipt["lines"][0]["rate"],
                    "description": receipt["lines"][0]["description"],
                    "unit_id": receipt["lines"][0]["unit_id"],
                }
            ],
        },
    )
    assert patched.status_code == 200, patched.text
    posted = await _post_grn(client, headers, receipt["id"], patched.json()["data"]["version"])
    assert posted.status_code == 409, posted.text
    assert posted.json()["error"]["code"] == "GRN_OVER_RECEIPT"


@pytest.mark.asyncio
async def test_unmapped_supplier_sku_blocks_post_not_save(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    supplier_id = await _create_supplier(client, headers)
    warehouse_id = await _main_warehouse(client, headers)
    created = await client.post(
        "/api/v1/goods-receipts",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "warehouse_id": warehouse_id,
            "lines": [
                {
                    "supplier_sku": "UNMAPPED-SKU",
                    "description": "Air extra",
                    "quantity": "1",
                    "rate": "10.0000",
                    "unit_id": ids["pcs"],
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    posted = await _post_grn(
        client, headers, created.json()["data"]["id"], created.json()["data"]["version"]
    )
    assert posted.status_code == 409, posted.text
    assert posted.json()["error"]["code"] == "SUPPLIER_SKU_NOT_MAPPED"


@pytest.mark.asyncio
async def test_qc_product_is_held_until_inspection_approved(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _issue_tracked_po(client, headers, quantity="5", requires_qc=True)
    created = await _create_from_po(client, headers, ctx["order"]["id"])
    posted = await _post_grn(
        client, headers, created["body"]["data"]["id"], created["body"]["data"]["version"]
    )
    assert posted.status_code == 200, posted.text
    assert posted.json()["data"]["qc_status"] == "PENDING"
    stock = await client.get(f"/api/v1/stock?product_id={ctx['product_id']}", headers=headers)
    row = stock.json()["data"][0]
    assert Decimal(row["qty_on_hand"]) == Decimal("5")
    assert Decimal(row["qty_quality_hold"]) == Decimal("5")
    assert Decimal(row["qty_available"]) == Decimal("0")

    inspections = await client.get(
        f"/api/v1/quality-inspections?goods_receipt_id={posted.json()['data']['id']}",
        headers=headers,
    )
    assert inspections.status_code == 200, inspections.text
    assert len(inspections.json()["data"]) == 1
    qi = inspections.json()["data"][0]
    assert qi["status"] == "DRAFT"

    dest = await client.post(
        "/api/v1/warehouses",
        headers=headers,
        json={"code": f"WH-{uuid4().hex[:8]}", "name": "Other"},
    )
    transfer = await client.post(
        "/api/v1/stock-transfers",
        headers=headers,
        json={
            "from_warehouse_id": ctx["warehouse_id"],
            "to_warehouse_id": dest.json()["data"]["id"],
            "lines": [{"product_id": ctx["product_id"], "qty": "1"}],
        },
    )
    assert transfer.status_code == 201, transfer.text
    rejected = await client.post(
        f"/api/v1/stock-transfers/{transfer.json()['data']['id']}/post",
        headers=_idempotent(headers, transfer.json()["data"]["version"]),
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error"]["code"] == "INVENTORY_INSUFFICIENT_STOCK"

    approved = await client.post(
        f"/api/v1/quality-inspections/{qi['id']}/approve",
        headers=_idempotent(headers, qi["version"]),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "APPROVED"
    stock_after = await client.get(f"/api/v1/stock?product_id={ctx['product_id']}", headers=headers)
    cleared = stock_after.json()["data"][0]
    assert Decimal(cleared["qty_quality_hold"]) == Decimal("0")
    assert Decimal(cleared["qty_available"]) == Decimal("5")


@pytest.mark.asyncio
async def test_cancel_posted_grn_restores_po_and_layers(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _issue_tracked_po(client, headers, quantity="3")
    created = await _create_from_po(client, headers, ctx["order"]["id"])
    posted = await _post_grn(
        client, headers, created["body"]["data"]["id"], created["body"]["data"]["version"]
    )
    assert posted.status_code == 200, posted.text
    cancelled = await client.post(
        f"/api/v1/goods-receipts/{posted.json()['data']['id']}/cancel",
        headers=_idempotent(headers, posted.json()["data"]["version"]),
        json={"reason": "wrong carton count"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["status"] == "CANCELLED"
    po = await client.get(f"/api/v1/purchase-orders/{ctx['order']['id']}", headers=headers)
    assert po.json()["data"]["receipt_status"] == "NOT_RECEIVED"
    stock = await client.get(f"/api/v1/stock?product_id={ctx['product_id']}", headers=headers)
    row = stock.json()["data"][0]
    assert Decimal(row["qty_on_hand"]) == Decimal("0")
    assert Decimal(row["qty_incoming"]) == Decimal("3")
    layers = await client.get(f"/api/v1/stock/{row['id']}/layers", headers=headers)
    remaining = sum(Decimal(item["qty_remaining"]) for item in layers.json()["data"])
    assert remaining == Decimal("0")


@pytest.mark.asyncio
async def test_cancel_posted_grn_refused_after_qi_approve(client: AsyncClient) -> None:
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
    approved = await client.post(
        f"/api/v1/quality-inspections/{qi['id']}/approve",
        headers=_idempotent(headers, qi["version"]),
    )
    assert approved.status_code == 200, approved.text
    cancelled = await client.post(
        f"/api/v1/goods-receipts/{posted.json()['data']['id']}/cancel",
        headers=_idempotent(headers, posted.json()["data"]["version"]),
    )
    assert cancelled.status_code == 409, cancelled.text
    assert cancelled.json()["error"]["code"] == "GRN_CANNOT_CANCEL"


@pytest.mark.asyncio
async def test_untracked_receive_updates_po_only(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _issue_tracked_po(client, headers, quantity="2", track_inventory=False)
    created = await _create_from_po(client, headers, ctx["order"]["id"])
    posted = await _post_grn(
        client, headers, created["body"]["data"]["id"], created["body"]["data"]["version"]
    )
    assert posted.status_code == 200, posted.text
    po = await client.get(f"/api/v1/purchase-orders/{ctx['order']['id']}", headers=headers)
    assert po.json()["data"]["receipt_status"] == "RECEIVED"
    assert Decimal(po.json()["data"]["lines"][0]["qty_received"]) == Decimal("2")
    stock = await client.get(f"/api/v1/stock?product_id={ctx['product_id']}", headers=headers)
    assert stock.json()["data"] == []


@pytest.mark.asyncio
async def test_direct_grn_posts_without_purchase_order(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    supplier_id = await _create_supplier(client, headers)
    product_id = await _create_product(client, headers, ids, track_inventory=True)
    warehouse_id = await _main_warehouse(client, headers)
    created = await client.post(
        "/api/v1/goods-receipts",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "warehouse_id": warehouse_id,
            "lines": [{"product_id": product_id, "quantity": "2", "rate": "25.0000"}],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["purchase_order_id"] is None
    posted = await _post_grn(
        client, headers, created.json()["data"]["id"], created.json()["data"]["version"]
    )
    assert posted.status_code == 200, posted.text
    stock = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    row = stock.json()["data"][0]
    assert Decimal(row["qty_on_hand"]) == Decimal("2")
    assert Decimal(row["qty_available"]) == Decimal("2")
    layers = await client.get(f"/api/v1/stock/{row['id']}/layers", headers=headers)
    assert Decimal(layers.json()["data"][0]["unit_cost"]) == Decimal("25.0000")

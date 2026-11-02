"""Goods receipt posting accepts lines entered in product unit 2."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.purchase_orders.test_routes import (
    _create_order,
    _create_supplier,
    _if_match,
    _seeded_ids,
)
from tests.api.inventory_management.goods_receipts.test_routes import (
    _create_from_po,
    _post_grn,
)
from tests.conftest import login_headers, provision_admin


async def _unit_id(client: AsyncClient, headers: dict[str, str], code: str) -> str:
    units = await client.get("/api/v1/units?page_size=100", headers=headers)
    assert units.status_code == 200, units.text
    return next(item["id"] for item in units.json()["data"] if item["code"] == code)


async def _product_with_unit2(
    client: AsyncClient, headers: dict[str, str], ids: dict[str, str]
) -> tuple[str, str, str]:
    pcs_id = ids["pcs"]
    box_id = await _unit_id(client, headers, "BOX")
    suffix = uuid4().hex[:8]
    created = await client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "sku": f"U2-{suffix}",
            "name": f"Pack {suffix}",
            "unit_id": pcs_id,
            "secondary_unit_id": box_id,
            "secondary_unit_factor": "10",
            "selling_rate": "1.0000",
            "purchase_rate": "100.0000",
            "tax_id": ids["standard_tax"],
            "track_inventory": True,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"], pcs_id, box_id


@pytest.mark.asyncio
async def test_post_goods_receipt_line_in_unit2_increases_stock_in_pieces(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    product_id, pcs_id, box_id = await _product_with_unit2(client, headers, ids)
    supplier_id = await _create_supplier(client, headers)
    order = await _create_order(
        client, headers, supplier_id=supplier_id, product_id=product_id, quantity="100"
    )
    issued = await client.post(
        f"/api/v1/purchase-orders/{order['body']['data']['id']}/issue",
        headers=_if_match(headers, order["body"]["data"]["version"]),
    )
    assert issued.status_code == 200, issued.text
    po = issued.json()["data"]

    created = await _create_from_po(client, headers, po["id"])
    assert created["status_code"] == 201, created["text"]
    receipt = created["body"]["data"]
    line = receipt["lines"][0]
    patched = await client.patch(
        f"/api/v1/goods-receipts/{receipt['id']}",
        headers=_if_match(headers, receipt["version"]),
        json={
            "version": receipt["version"],
            "lines": [
                {
                    "purchase_order_line_id": line["purchase_order_line_id"],
                    "product_id": product_id,
                    "quantity": "2",
                    "unit_id": box_id,
                    "rate": "1000.0000",
                    "description": line["description"],
                }
            ],
        },
    )
    assert patched.status_code == 200, patched.text
    saved = patched.json()["data"]["lines"][0]
    assert saved["unit_id"] == pcs_id
    assert Decimal(saved["quantity"]) == Decimal("20.000000")
    assert Decimal(saved["rate"]) == Decimal("100.0000")

    posted = await _post_grn(client, headers, receipt["id"], patched.json()["data"]["version"])
    assert posted.status_code == 200, posted.text

    stock = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    assert stock.status_code == 200, stock.text
    rows = stock.json()["data"]
    assert len(rows) == 1
    assert Decimal(rows[0]["qty_on_hand"]) == Decimal("20.000000")


@pytest.mark.asyncio
async def test_create_gr_from_po_when_unit2_is_pieces(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    pcs_id = ids["pcs"]
    ctn_id = await _unit_id(client, headers, "BOX")
    suffix = uuid4().hex[:8]
    product = await client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "sku": f"INV-{suffix}",
            "name": f"Inverted {suffix}",
            "unit_id": ctn_id,
            "secondary_unit_id": pcs_id,
            "secondary_unit_factor": "10",
            "selling_rate": "1.0000",
            "purchase_rate": "100.0000",
            "tax_id": ids["standard_tax"],
            "track_inventory": True,
        },
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["data"]["id"]
    supplier_id = await _create_supplier(client, headers)
    order = await _create_order(
        client,
        headers,
        supplier_id=supplier_id,
        product_id=product_id,
        quantity="100",
    )
    po_id = order["body"]["data"]["id"]
    po_line_id = order["body"]["data"]["lines"][0]["id"]
    patched_po = await client.patch(
        f"/api/v1/purchase-orders/{po_id}",
        headers=_if_match(headers, order["body"]["data"]["version"]),
        json={
            "version": order["body"]["data"]["version"],
            "lines": [
                {
                    "id": po_line_id,
                    "product_id": product_id,
                    "quantity": "100",
                    "unit_id": pcs_id,
                    "rate": "10.0000",
                    "description": "Line",
                }
            ],
        },
    )
    assert patched_po.status_code == 200, patched_po.text
    issued = await client.post(
        f"/api/v1/purchase-orders/{po_id}/issue",
        headers=_if_match(headers, patched_po.json()["data"]["version"]),
    )
    assert issued.status_code == 200, issued.text

    created = await _create_from_po(client, headers, po_id)
    assert created["status_code"] == 201, created["text"]
    line = created["body"]["data"]["lines"][0]
    assert line["unit_id"] == pcs_id
    assert Decimal(line["quantity"]) == Decimal("100.000000")

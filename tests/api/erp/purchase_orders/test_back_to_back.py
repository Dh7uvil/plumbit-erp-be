"""API tests for back-to-back purchase orders from a sales order."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.purchase_orders.test_routes import _create_supplier
from tests.api.erp.sales_orders.test_routes import (
    _create_customer,
    _create_product,
    _if_match,
    _seeded_ids,
)
from tests.conftest import login_headers, provision_admin


async def _confirm_sales_order(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    customer_id: str,
    lines: list[dict[str, object]],
) -> dict[str, object]:
    created = await client.post(
        "/api/v1/sales-orders",
        headers=headers,
        json={"customer_id": customer_id, "lines": lines},
    )
    assert created.status_code == 201, created.text
    confirmed = await client.post(
        f"/api/v1/sales-orders/{created.json()['data']['id']}/confirm",
        headers=_if_match(headers, created.json()["data"]["version"]),
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()["data"]


async def _preferred_catalog(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    supplier_id: str,
    product_id: str,
    currency_id: str,
) -> dict[str, object]:
    suffix = uuid4().hex[:8]
    created = await client.post(
        "/api/v1/supplier-products",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "product_id": product_id,
            "supplier_sku": f"VEN-{suffix}",
            "supplier_item_name": f"Vendor pipe {suffix}",
            "price": "75.0000",
            "currency_id": currency_id,
            "is_preferred_supplier": True,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]


@pytest.mark.asyncio
async def test_plan_groups_preferred_supplier_and_unassigned(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    mapped = await _create_product(client, headers, ids)
    unmapped = await _create_product(client, headers, ids)
    supplier_id = await _create_supplier(client, headers)
    catalog = await _preferred_catalog(
        client,
        headers,
        supplier_id=supplier_id,
        product_id=mapped,
        currency_id=ids["aed"],
    )
    order = await _confirm_sales_order(
        client,
        headers,
        customer_id=customer_id,
        lines=[
            {"product_id": mapped, "quantity": "10"},
            {"product_id": unmapped, "quantity": "4"},
            {"description": "Freight", "quantity": "1", "rate": "50"},
        ],
    )
    draft_plan = await client.get(
        f"/api/v1/sales-orders/{order['id']}/purchase-order-plan",
        headers=headers,
    )
    assert draft_plan.status_code == 200, draft_plan.text

    plan = draft_plan.json()["data"]
    assert len(plan["groups"]) == 1
    group = plan["groups"][0]
    assert group["supplier_id"] == supplier_id
    assert group["lines"][0]["product_id"] == mapped
    assert group["lines"][0]["supplier_product_id"] == catalog["id"]
    assert Decimal(group["lines"][0]["qty_uncovered"]) == Decimal("10")
    unassigned_products = {item["product_id"] for item in plan["unassigned"]}
    assert unmapped in unassigned_products
    assert None in unassigned_products or any(
        item["product_id"] is None for item in plan["unassigned"]
    )


@pytest.mark.asyncio
async def test_create_coverage_overcommit_and_cancel(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    supplier_id = await _create_supplier(client, headers)
    catalog = await _preferred_catalog(
        client,
        headers,
        supplier_id=supplier_id,
        product_id=product_id,
        currency_id=ids["aed"],
    )
    order = await _confirm_sales_order(
        client,
        headers,
        customer_id=customer_id,
        lines=[{"product_id": product_id, "quantity": "10"}],
    )
    so_line_id = order["lines"][0]["id"]
    empty = await client.get(
        f"/api/v1/sales-orders/{order['id']}/coverage",
        headers=headers,
    )
    assert empty.status_code == 200, empty.text
    assert Decimal(empty.json()["data"]["lines"][0]["qty_uncovered"]) == Decimal("10")

    key = str(uuid4())
    payload = {
        "groups": [
            {
                "supplier_id": supplier_id,
                "lines": [
                    {
                        "sales_order_line_id": so_line_id,
                        "quantity": "6",
                        "supplier_product_id": catalog["id"],
                    }
                ],
            }
        ]
    }
    created = await client.post(
        f"/api/v1/sales-orders/{order['id']}/purchase-orders",
        headers={**headers, "Idempotency-Key": key},
        json=payload,
    )
    assert created.status_code == 201, created.text
    orders = created.json()["data"]
    assert len(orders) == 1
    assert orders[0]["source_sales_order_id"] == order["id"]
    assert orders[0]["lines"][0]["source_sales_order_line_id"] == so_line_id
    assert orders[0]["lines"][0]["supplier_sku"] == catalog["supplier_sku"]

    replay = await client.post(
        f"/api/v1/sales-orders/{order['id']}/purchase-orders",
        headers={**headers, "Idempotency-Key": key},
        json=payload,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["data"][0]["id"] == orders[0]["id"]

    listed = await client.get(
        f"/api/v1/purchase-orders?source_sales_order_id={order['id']}",
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["data"][0]["id"] == orders[0]["id"]

    covered = await client.get(
        f"/api/v1/sales-orders/{order['id']}/coverage",
        headers=headers,
    )
    line = covered.json()["data"]["lines"][0]
    assert Decimal(line["qty_covered"]) == Decimal("6")
    assert Decimal(line["qty_uncovered"]) == Decimal("4")
    assert line["purchase_orders"][0]["id"] == orders[0]["id"]

    exceeded = await client.post(
        f"/api/v1/sales-orders/{order['id']}/purchase-orders",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "groups": [
                {
                    "supplier_id": supplier_id,
                    "lines": [
                        {
                            "sales_order_line_id": so_line_id,
                            "quantity": "5",
                            "supplier_product_id": catalog["id"],
                        }
                    ],
                }
            ]
        },
    )
    assert exceeded.status_code == 409, exceeded.text
    assert exceeded.json()["error"]["code"] == "PO_COVERAGE_EXCEEDED"

    cancelled = await client.post(
        f"/api/v1/purchase-orders/{orders[0]['id']}/cancel",
        headers=_if_match(headers, orders[0]["version"]),
        json={"reason": "Supplier dropped"},
    )
    assert cancelled.status_code == 200, cancelled.text
    after_cancel = await client.get(
        f"/api/v1/sales-orders/{order['id']}/coverage",
        headers=headers,
    )
    assert Decimal(after_cancel.json()["data"]["lines"][0]["qty_uncovered"]) == Decimal("10")
    assert after_cancel.json()["data"]["lines"][0]["purchase_orders"] == []


@pytest.mark.asyncio
async def test_plan_refuses_unconfirmed_sales_order(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await client.post(
        "/api/v1/sales-orders",
        headers=headers,
        json={
            "customer_id": customer_id,
            "lines": [{"product_id": product_id, "quantity": "2"}],
        },
    )
    assert created.status_code == 201, created.text
    plan = await client.get(
        f"/api/v1/sales-orders/{created.json()['data']['id']}/purchase-order-plan",
        headers=headers,
    )
    assert plan.status_code == 409, plan.text
    assert plan.json()["error"]["code"] == "SALES_ORDER_NOT_CONFIRMED"

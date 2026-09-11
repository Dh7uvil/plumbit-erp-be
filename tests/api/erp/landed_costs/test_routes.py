"""API tests for landed cost allocation, post, cancel, and isolation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.api.erp.purchase_invoices.test_routes import _enable_books
from tests.api.erp.purchase_orders.test_routes import (
    _create_product,
    _create_supplier,
    _if_match,
    _seeded_ids,
)
from tests.api.erp.sales_orders.test_routes import _create_customer
from tests.api.erp.sales_orders.test_routes import _create_order as _create_sales_order
from tests.api.inventory_management.delivery_notes.test_routes import (
    _create_and_post_delivery_note,
)
from tests.api.inventory_management.goods_receipts.test_routes import (
    _create_from_po,
    _idempotent,
    _issue_tracked_po,
    _main_warehouse,
    _post_grn,
)
from tests.conftest import login_headers, provision_admin


async def _accounts(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    assert roles.status_code == 200, roles.text
    return {item["role"]: item["account_id"] for item in roles.json()["data"]}


async def _stock_row(
    client: AsyncClient, headers: dict[str, str], product_id: str
) -> dict[str, object]:
    stock = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    assert stock.status_code == 200, stock.text
    rows = stock.json()["data"]
    assert rows
    return rows[0]


async def _post_expense_bill(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    supplier_id: str,
    grn_id: str,
    rate: str,
    expense_category: str = "FREIGHT",
    description: str = "Ocean freight",
) -> dict[str, object]:
    created = await client.post(
        "/api/v1/purchase-invoices",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "bill_type": "EXPENSE",
            "goods_receipt_id": grn_id,
            "lines": [
                {
                    "line_type": "EXPENSE",
                    "description": description,
                    "quantity": "1",
                    "rate": rate,
                    "expense_category": expense_category,
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    posted = await client.post(
        f"/api/v1/purchase-invoices/{created.json()['data']['id']}/post",
        headers=_idempotent(headers, created.json()["data"]["version"]),
    )
    assert posted.status_code == 200, posted.text
    return posted.json()["data"]


async def _create_and_post_lc(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    charges: list[dict[str, object]],
    allocations: list[dict[str, object]],
    allocation_method: str = "VALUE",
) -> dict[str, object]:
    created = await client.post(
        "/api/v1/landed-costs",
        headers=headers,
        json={
            "allocation_method": allocation_method,
            "charges": charges,
            "allocations": allocations,
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    posted = await client.post(
        f"/api/v1/landed-costs/{row['id']}/post",
        headers=_idempotent(headers, row["version"]),
    )
    assert posted.status_code == 200, posted.text
    return posted.json()["data"]


async def _two_line_posted_grn(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    weights: tuple[str, str] | None = None,
) -> dict[str, object]:
    ids = await _seeded_ids(client, headers)
    supplier_id = await _create_supplier(client, headers)
    first = await _create_product(
        client, headers, ids, track_inventory=True, purchase_rate="80.0000"
    )
    second = await _create_product(
        client, headers, ids, track_inventory=True, purchase_rate="40.0000"
    )
    created = await client.post(
        "/api/v1/purchase-orders",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "lines": [
                {"product_id": first, "quantity": "2", "rate": "80.0000"},
                {"product_id": second, "quantity": "2", "rate": "40.0000"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    issued = await client.post(
        f"/api/v1/purchase-orders/{created.json()['data']['id']}/issue",
        headers=_if_match(headers, created.json()["data"]["version"]),
    )
    assert issued.status_code == 200, issued.text
    receipt = await _create_from_po(client, headers, issued.json()["data"]["id"])
    assert receipt["status_code"] == 201, receipt["text"]
    grn = receipt["body"]["data"]
    if weights is not None:
        patched = await client.patch(
            f"/api/v1/goods-receipts/{grn['id']}",
            headers={**headers, "If-Match": str(grn["version"])},
            json={
                "lines": [
                    {
                        "purchase_order_line_id": line["purchase_order_line_id"],
                        "product_id": line["product_id"],
                        "quantity": line["quantity"],
                        "rate": line["rate"],
                        "net_weight": weight,
                    }
                    for line, weight in zip(grn["lines"], weights, strict=True)
                ]
            },
        )
        assert patched.status_code == 200, patched.text
        grn = patched.json()["data"]
    posted = await _post_grn(client, headers, grn["id"], grn["version"])
    assert posted.status_code == 200, posted.text
    return {
        "grn": posted.json()["data"],
        "supplier_id": supplier_id,
        "product_ids": [first, second],
        "warehouse_id": await _main_warehouse(client, headers),
    }


@pytest.mark.asyncio
async def test_allocate_freight_and_duty_by_value_and_weight(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    ctx = await _two_line_posted_grn(client, headers, weights=("1", "3"))
    grn = ctx["grn"]
    freight = await _post_expense_bill(
        client, headers, supplier_id=str(ctx["supplier_id"]), grn_id=grn["id"], rate="30.0000"
    )
    duty = await _post_expense_bill(
        client,
        headers,
        supplier_id=str(ctx["supplier_id"]),
        grn_id=grn["id"],
        rate="10.0000",
        expense_category="CUSTOMS_DUTY",
        description="Customs duty",
    )
    charges = [
        {"purchase_invoice_line_id": freight["lines"][0]["id"]},
        {"purchase_invoice_line_id": duty["lines"][0]["id"]},
    ]
    allocations = [{"goods_receipt_line_id": line["id"]} for line in grn["lines"]]
    by_value = await _create_and_post_lc(
        client, headers, charges=charges, allocations=allocations, allocation_method="VALUE"
    )
    amounts = {
        item["goods_receipt_line_id"]: Decimal(item["allocated_amount"])
        for item in by_value["allocations"]
    }
    first_id, second_id = grn["lines"][0]["id"], grn["lines"][1]["id"]
    assert amounts[first_id] == Decimal("26.6667")
    assert amounts[second_id] == Decimal("13.3333")

    cancelled = await client.post(
        f"/api/v1/landed-costs/{by_value['id']}/cancel",
        headers=_idempotent(headers, by_value["version"]),
        json={"reason": "Reallocate by weight"},
    )
    assert cancelled.status_code == 200, cancelled.text

    by_weight = await _create_and_post_lc(
        client, headers, charges=charges, allocations=allocations, allocation_method="WEIGHT"
    )
    weight_amounts = {
        item["goods_receipt_line_id"]: Decimal(item["allocated_amount"])
        for item in by_weight["allocations"]
    }
    assert weight_amounts[first_id] == Decimal("10.0000")
    assert weight_amounts[second_id] == Decimal("30.0000")


@pytest.mark.asyncio
async def test_consumed_qty_posts_landed_cost_variance(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    ctx = await _issue_tracked_po(client, headers, quantity="4")
    created = await _create_from_po(client, headers, ctx["order"]["id"])
    posted_grn = await _post_grn(
        client, headers, created["body"]["data"]["id"], created["body"]["data"]["version"]
    )
    assert posted_grn.status_code == 200, posted_grn.text
    grn = posted_grn.json()["data"]
    product_id = str(ctx["product_id"])
    customer_id = await _create_customer(client, headers)
    so = await _create_sales_order(
        client, headers, customer_id=customer_id, product_id=product_id, quantity="2"
    )
    assert so["status_code"] == 201, so["text"]
    confirmed = await client.post(
        f"/api/v1/sales-orders/{so['body']['data']['id']}/confirm",
        headers=_if_match(headers, so["body"]["data"]["version"]),
    )
    assert confirmed.status_code == 200, confirmed.text
    await _create_and_post_delivery_note(client, headers, confirmed.json()["data"]["id"])

    freight = await _post_expense_bill(
        client, headers, supplier_id=str(ctx["supplier_id"]), grn_id=grn["id"], rate="40.0000"
    )
    posted = await _create_and_post_lc(
        client,
        headers,
        charges=[{"purchase_invoice_line_id": freight["lines"][0]["id"]}],
        allocations=[{"goods_receipt_line_id": grn["lines"][0]["id"]}],
    )
    journal = await client.get(f"/api/v1/landed-costs/{posted['id']}/journal", headers=headers)
    assert journal.status_code == 200, journal.text
    accounts = await _accounts(client, headers)
    by_account = {line["account_id"]: line for line in journal.json()["data"]["lines"]}
    assert Decimal(by_account[accounts["INVENTORY"]]["debit"]) == Decimal("20.0000")
    assert Decimal(by_account[accounts["LANDED_COST_VARIANCE"]]["debit"]) == Decimal("20.0000")
    assert Decimal(by_account[accounts["FREIGHT_IN"]]["credit"]) == Decimal("40.0000")


@pytest.mark.asyncio
async def test_weight_without_net_weight_refused(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _issue_tracked_po(client, headers, quantity="4")
    created = await _create_from_po(client, headers, ctx["order"]["id"])
    posted_grn = await _post_grn(
        client, headers, created["body"]["data"]["id"], created["body"]["data"]["version"]
    )
    grn = posted_grn.json()["data"]
    freight = await _post_expense_bill(
        client, headers, supplier_id=str(ctx["supplier_id"]), grn_id=grn["id"], rate="10.0000"
    )
    created_lc = await client.post(
        "/api/v1/landed-costs",
        headers=headers,
        json={
            "allocation_method": "WEIGHT",
            "charges": [{"purchase_invoice_line_id": freight["lines"][0]["id"]}],
            "allocations": [{"goods_receipt_line_id": grn["lines"][0]["id"]}],
        },
    )
    assert created_lc.status_code == 422, created_lc.text
    assert created_lc.json()["error"]["code"] == "LANDED_COST_WEIGHT_REQUIRED"


@pytest.mark.asyncio
async def test_double_allocate_same_bill_line_refused(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _issue_tracked_po(client, headers, quantity="4")
    created = await _create_from_po(client, headers, ctx["order"]["id"])
    posted_grn = await _post_grn(
        client, headers, created["body"]["data"]["id"], created["body"]["data"]["version"]
    )
    grn = posted_grn.json()["data"]
    freight = await _post_expense_bill(
        client, headers, supplier_id=str(ctx["supplier_id"]), grn_id=grn["id"], rate="10.0000"
    )
    charge = {"purchase_invoice_line_id": freight["lines"][0]["id"]}
    allocation = {"goods_receipt_line_id": grn["lines"][0]["id"]}
    await _create_and_post_lc(client, headers, charges=[charge], allocations=[allocation])
    second = await client.post(
        "/api/v1/landed-costs",
        headers=headers,
        json={"charges": [charge], "allocations": [allocation]},
    )
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "LANDED_COST_LINE_OVER_ALLOCATED"


@pytest.mark.asyncio
async def test_cancel_restores_remaining_layer_cost(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _issue_tracked_po(client, headers, quantity="4")
    created = await _create_from_po(client, headers, ctx["order"]["id"])
    posted_grn = await _post_grn(
        client, headers, created["body"]["data"]["id"], created["body"]["data"]["version"]
    )
    grn = posted_grn.json()["data"]
    product_id = str(ctx["product_id"])
    freight = await _post_expense_bill(
        client, headers, supplier_id=str(ctx["supplier_id"]), grn_id=grn["id"], rate="40.0000"
    )
    posted = await _create_and_post_lc(
        client,
        headers,
        charges=[{"purchase_invoice_line_id": freight["lines"][0]["id"]}],
        allocations=[{"goods_receipt_line_id": grn["lines"][0]["id"]}],
    )
    stock = await _stock_row(client, headers, product_id)
    layers = await client.get(f"/api/v1/stock/{stock['id']}/layers", headers=headers)
    assert Decimal(layers.json()["data"][0]["landed_unit_cost"]) == Decimal("90.0000")
    cancelled = await client.post(
        f"/api/v1/landed-costs/{posted['id']}/cancel",
        headers=_idempotent(headers, posted["version"]),
        json={"reason": "Restore layer cost"},
    )
    assert cancelled.status_code == 200, cancelled.text
    layers = await client.get(f"/api/v1/stock/{stock['id']}/layers", headers=headers)
    assert Decimal(layers.json()["data"][0]["landed_unit_cost"]) == Decimal("80.0000")


@pytest.mark.asyncio
async def test_period_lock_blocks_landed_cost_post(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _issue_tracked_po(client, headers, quantity="4")
    created = await _create_from_po(client, headers, ctx["order"]["id"])
    posted_grn = await _post_grn(
        client, headers, created["body"]["data"]["id"], created["body"]["data"]["version"]
    )
    grn = posted_grn.json()["data"]
    freight = await _post_expense_bill(
        client, headers, supplier_id=str(ctx["supplier_id"]), grn_id=grn["id"], rate="10.0000"
    )
    draft = await client.post(
        "/api/v1/landed-costs",
        headers=headers,
        json={
            "charges": [{"purchase_invoice_line_id": freight["lines"][0]["id"]}],
            "allocations": [{"goods_receipt_line_id": grn["lines"][0]["id"]}],
        },
    )
    assert draft.status_code == 201, draft.text
    locked = await client.patch(
        "/api/v1/period-lock",
        headers=headers,
        json={"hard_lock_date": datetime.now(UTC).date().isoformat()},
    )
    assert locked.status_code == 200, locked.text
    posted = await client.post(
        f"/api/v1/landed-costs/{draft.json()['data']['id']}/post",
        headers=_idempotent(headers, draft.json()["data"]["version"]),
    )
    assert posted.status_code == 409, posted.text
    assert posted.json()["error"]["code"] == "PERIOD_LOCKED"


@pytest.mark.asyncio
async def test_landed_cost_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    ctx = await _issue_tracked_po(client, headers_a, quantity="4")
    created = await _create_from_po(client, headers_a, ctx["order"]["id"])
    posted_grn = await _post_grn(
        client, headers_a, created["body"]["data"]["id"], created["body"]["data"]["version"]
    )
    grn = posted_grn.json()["data"]
    freight = await _post_expense_bill(
        client, headers_a, supplier_id=str(ctx["supplier_id"]), grn_id=grn["id"], rate="10.0000"
    )
    draft = await client.post(
        "/api/v1/landed-costs",
        headers=headers_a,
        json={
            "charges": [{"purchase_invoice_line_id": freight["lines"][0]["id"]}],
            "allocations": [{"goods_receipt_line_id": grn["lines"][0]["id"]}],
        },
    )
    assert draft.status_code == 201, draft.text
    landed_cost_id = draft.json()["data"]["id"]
    fetched = await client.get(f"/api/v1/landed-costs/{landed_cost_id}", headers=headers_b)
    assert fetched.status_code == 404
    listed = await client.get("/api/v1/landed-costs", headers=headers_b)
    assert listed.status_code == 200
    assert all(item["id"] != landed_cost_id for item in listed.json()["data"])


@pytest.mark.asyncio
async def test_dispatch_after_revalue_consumes_landed_cost(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    ctx = await _issue_tracked_po(client, headers, quantity="4")
    created = await _create_from_po(client, headers, ctx["order"]["id"])
    posted_grn = await _post_grn(
        client, headers, created["body"]["data"]["id"], created["body"]["data"]["version"]
    )
    grn = posted_grn.json()["data"]
    freight = await _post_expense_bill(
        client, headers, supplier_id=str(ctx["supplier_id"]), grn_id=grn["id"], rate="40.0000"
    )
    await _create_and_post_lc(
        client,
        headers,
        charges=[{"purchase_invoice_line_id": freight["lines"][0]["id"]}],
        allocations=[{"goods_receipt_line_id": grn["lines"][0]["id"]}],
    )
    product_id = str(ctx["product_id"])
    stock = await _stock_row(client, headers, product_id)
    layers = await client.get(f"/api/v1/stock/{stock['id']}/layers", headers=headers)
    assert Decimal(layers.json()["data"][0]["landed_unit_cost"]) == Decimal("90.0000")
    customer_id = await _create_customer(client, headers)
    so = await _create_sales_order(
        client, headers, customer_id=customer_id, product_id=product_id, quantity="4"
    )
    confirmed = await client.post(
        f"/api/v1/sales-orders/{so['body']['data']['id']}/confirm",
        headers=_if_match(headers, so["body"]["data"]["version"]),
    )
    assert confirmed.status_code == 200, confirmed.text
    await _create_and_post_delivery_note(client, headers, confirmed.json()["data"]["id"])
    movements = await client.get(
        f"/api/v1/stock-movements?product_id={product_id}&page_size=100",
        headers=headers,
    )
    assert movements.status_code == 200, movements.text
    outbound = next(
        item for item in movements.json()["data"] if Decimal(item["qty"]) < 0
    )
    assert Decimal(outbound["unit_cost"]) == Decimal("90.0000")
    assert Decimal(outbound["value"]) == Decimal("-360.0000")

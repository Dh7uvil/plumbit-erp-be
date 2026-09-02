"""API tests for stock balances, adjustments, and transfers."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.auth.models import Tenant
from app.db.session import async_session_factory, transaction
from app.inventory_management.stock.models import StockBalance
from tests.conftest import login_headers, provision_admin


async def _seeded(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    units = await client.get("/api/v1/units?page_size=100", headers=headers)
    assert units.status_code == 200, units.text
    pcs = next(item for item in units.json()["data"] if item["code"] == "PCS")
    warehouses = await client.get("/api/v1/warehouses?page_size=100", headers=headers)
    assert warehouses.status_code == 200, warehouses.text
    main = next(item for item in warehouses.json()["data"] if item["code"] == "MAIN")
    return {"pcs": pcs["id"], "main": main["id"]}


async def _create_product(
    client: AsyncClient,
    headers: dict[str, str],
    ids: dict[str, str],
    *,
    track_inventory: bool = True,
    item_type: str = "PRODUCT",
    category_id: str | None = None,
) -> str:
    suffix = uuid4().hex[:8]
    payload: dict[str, object] = {
        "sku": f"SKU-{suffix}",
        "name": f"Pipe {suffix}",
        "item_type": item_type,
        "unit_id": ids["pcs"],
        "track_inventory": track_inventory,
        "selling_rate": "10.0000",
    }
    if category_id is not None:
        payload["category_id"] = category_id
    response = await client.post(
        "/api/v1/products",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


async def _create_warehouse(client: AsyncClient, headers: dict[str, str]) -> str:
    suffix = uuid4().hex[:8]
    response = await client.post(
        "/api/v1/warehouses",
        headers=headers,
        json={"code": f"WH-{suffix}", "name": f"Warehouse {suffix}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def _if_match(
    headers: dict[str, str], version: object, *, key: str | None = None
) -> dict[str, str]:
    extra = {**headers, "If-Match": str(version)}
    if key is not None:
        extra["Idempotency-Key"] = key
    return extra


async def _create_adjustment(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    warehouse_id: str,
    product_id: str,
    reason: str = "OPENING_STOCK",
    qty_delta: str | None = "10",
    qty_counted: str | None = None,
) -> dict[str, object]:
    line: dict[str, object] = {"product_id": product_id}
    if qty_delta is not None:
        line["qty_delta"] = qty_delta
    if qty_counted is not None:
        line["qty_counted"] = qty_counted
    response = await client.post(
        "/api/v1/stock-adjustments",
        headers=headers,
        json={"warehouse_id": warehouse_id, "reason": reason, "lines": [line]},
    )
    return {"status_code": response.status_code, "body": response.json(), "text": response.text}


async def _post_document(
    client: AsyncClient,
    headers: dict[str, str],
    path: str,
    version: object,
    *,
    key: str | None = None,
) -> object:
    idempotency = key if key is not None else uuid4().hex
    response = await client.post(path, headers=_if_match(headers, version, key=idempotency))
    return response


@pytest.mark.asyncio
async def test_stock_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    ids = await _seeded(client, headers_a)
    product_id = await _create_product(client, headers_a, ids)
    created = await _create_adjustment(
        client, headers_a, warehouse_id=ids["main"], product_id=product_id
    )
    assert created["status_code"] == 201, created["text"]
    adjustment_id = created["body"]["data"]["id"]
    fetched = await client.get(f"/api/v1/stock-adjustments/{adjustment_id}", headers=headers_b)
    assert fetched.status_code == 404
    listed = await client.get("/api/v1/stock-adjustments", headers=headers_b)
    assert listed.status_code == 200
    assert all(item["id"] != adjustment_id for item in listed.json()["data"])
    stock = await client.get("/api/v1/stock", headers=headers_b)
    assert stock.status_code == 200
    assert stock.json()["data"] == []


@pytest.mark.asyncio
async def test_draft_save_does_not_move_stock(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_adjustment(
        client, headers, warehouse_id=ids["main"], product_id=product_id
    )
    assert created["status_code"] == 201, created["text"]
    data = created["body"]["data"]
    assert data["status"] == "DRAFT"
    assert data["is_posted"] is False
    assert data["document_number"].startswith("STA-")
    assert {"post", "cancel", "delete", "clone"}.issubset(data["available_actions"])
    stock = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    assert stock.status_code == 200
    assert stock.json()["data"] == []


@pytest.mark.asyncio
async def test_post_opening_stock_moves_qty_and_is_idempotent(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_adjustment(
        client, headers, warehouse_id=ids["main"], product_id=product_id, qty_delta="25"
    )
    assert created["status_code"] == 201, created["text"]
    doc = created["body"]["data"]
    key = uuid4().hex
    posted = await client.post(
        f"/api/v1/stock-adjustments/{doc['id']}/post",
        headers=_if_match(headers, doc["version"], key=key),
    )
    assert posted.status_code == 200, posted.text
    posted_data = posted.json()["data"]
    assert posted_data["status"] == "POSTED"
    assert posted_data["is_posted"] is True
    assert posted_data["available_actions"] == ["clone"]
    assert Decimal(posted_data["lines"][0]["qty_booked"]) == Decimal("0")
    assert Decimal(posted_data["lines"][0]["qty_delta"]) == Decimal("25")

    stock = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    assert stock.status_code == 200, stock.text
    rows = stock.json()["data"]
    assert len(rows) == 1
    assert Decimal(rows[0]["qty_on_hand"]) == Decimal("25")
    assert Decimal(rows[0]["qty_available"]) == Decimal("25")
    assert Decimal(rows[0]["qty_reserved"]) == Decimal("0")

    replay = await client.post(
        f"/api/v1/stock-adjustments/{doc['id']}/post",
        headers=_if_match(headers, posted_data["version"], key=key),
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"]["id"] == posted_data["id"]
    stock_again = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    assert Decimal(stock_again.json()["data"][0]["qty_on_hand"]) == Decimal("25")

    second_key = await client.post(
        f"/api/v1/stock-adjustments/{doc['id']}/post",
        headers=_if_match(headers, posted_data["version"], key=uuid4().hex),
    )
    assert second_key.status_code == 200, second_key.text
    stock_third = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    assert Decimal(stock_third.json()["data"][0]["qty_on_hand"]) == Decimal("25")

    other = await _create_adjustment(
        client, headers, warehouse_id=ids["main"], product_id=product_id, qty_delta="1"
    )
    other_doc = other["body"]["data"]
    conflict = await client.post(
        f"/api/v1/stock-adjustments/{other_doc['id']}/post",
        headers=_if_match(headers, other_doc["version"], key=key),
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.asyncio
async def test_stale_if_match_on_adjustment(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_adjustment(
        client, headers, warehouse_id=ids["main"], product_id=product_id
    )
    doc = created["body"]["data"]
    stale = await client.patch(
        f"/api/v1/stock-adjustments/{doc['id']}",
        headers=_if_match(headers, 99),
        json={"notes": "stale", "version": 99},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "DOCUMENT_STALE"


@pytest.mark.asyncio
async def test_insufficient_stock_and_allow_negative(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_adjustment(
        client,
        headers,
        warehouse_id=ids["main"],
        product_id=product_id,
        reason="DAMAGE",
        qty_delta="-4",
    )
    assert created["status_code"] == 201, created["text"]
    doc = created["body"]["data"]
    rejected = await _post_document(
        client, headers, f"/api/v1/stock-adjustments/{doc['id']}/post", doc["version"]
    )
    assert rejected.status_code == 409, rejected.text
    error = rejected.json()["error"]
    assert error["code"] == "INVENTORY_INSUFFICIENT_STOCK"
    assert error["details"]["warehouse_code"] == "MAIN"
    assert error["details"]["product_id"] == product_id

    toggled = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"allow_negative_stock": True},
    )
    assert toggled.status_code == 200, toggled.text
    assert toggled.json()["data"]["allow_negative_stock"] is True

    allowed = await _post_document(
        client, headers, f"/api/v1/stock-adjustments/{doc['id']}/post", doc["version"]
    )
    assert allowed.status_code == 200, allowed.text
    stock = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    assert Decimal(stock.json()["data"][0]["qty_on_hand"]) == Decimal("-4")
    assert Decimal(stock.json()["data"][0]["qty_available"]) == Decimal("-4")


@pytest.mark.asyncio
async def test_transfer_moves_source_and_dest_using_available_qty(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    dest_id = await _create_warehouse(client, headers)
    product_id = await _create_product(client, headers, ids)
    opening = await _create_adjustment(
        client, headers, warehouse_id=ids["main"], product_id=product_id, qty_delta="10"
    )
    opening_doc = opening["body"]["data"]
    posted_open = await _post_document(
        client,
        headers,
        f"/api/v1/stock-adjustments/{opening_doc['id']}/post",
        opening_doc["version"],
    )
    assert posted_open.status_code == 200, posted_open.text

    transfer = await client.post(
        "/api/v1/stock-transfers",
        headers=headers,
        json={
            "from_warehouse_id": ids["main"],
            "to_warehouse_id": dest_id,
            "lines": [{"product_id": product_id, "qty": "4"}],
        },
    )
    assert transfer.status_code == 201, transfer.text
    doc = transfer.json()["data"]
    assert doc["document_number"].startswith("STR-")
    assert doc["status"] == "DRAFT"
    stock_before = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    assert Decimal(stock_before.json()["data"][0]["qty_on_hand"]) == Decimal("10")

    posted = await _post_document(
        client, headers, f"/api/v1/stock-transfers/{doc['id']}/post", doc["version"]
    )
    assert posted.status_code == 200, posted.text
    posted_data = posted.json()["data"]
    assert posted_data["status"] == "POSTED"
    assert Decimal(posted_data["lines"][0]["qty_source_before"]) == Decimal("10")
    assert Decimal(posted_data["lines"][0]["qty_dest_before"]) == Decimal("0")
    assert Decimal(posted_data["lines"][0]["qty_transferred"]) == Decimal("4")

    stock = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    by_warehouse = {item["warehouse_id"]: item for item in stock.json()["data"]}
    assert Decimal(by_warehouse[ids["main"]]["qty_on_hand"]) == Decimal("6")
    assert Decimal(by_warehouse[dest_id]["qty_on_hand"]) == Decimal("4")

    movements = await client.get(
        f"/api/v1/stock-movements?product_id={product_id}&source_id={doc['id']}",
        headers=headers,
    )
    assert movements.status_code == 200, movements.text
    types = {item["movement_type"] for item in movements.json()["data"]}
    assert types == {"TRANSFER_OUT", "TRANSFER_IN"}


@pytest.mark.asyncio
async def test_transfer_insufficient_uses_available_not_on_hand(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    dest_id = await _create_warehouse(client, headers)
    product_id = await _create_product(client, headers, ids)
    opening = await _create_adjustment(
        client, headers, warehouse_id=ids["main"], product_id=product_id, qty_delta="10"
    )
    opening_doc = opening["body"]["data"]
    posted_open = await _post_document(
        client,
        headers,
        f"/api/v1/stock-adjustments/{opening_doc['id']}/post",
        opening_doc["version"],
    )
    assert posted_open.status_code == 200, posted_open.text

    async with async_session_factory() as session, transaction(session):
        result = await session.execute(
            select(StockBalance).where(
                StockBalance.tenant_id == UUID(tenant_id),
                StockBalance.product_id == UUID(product_id),
            )
        )
        balance = result.scalar_one()
        balance.qty_reserved = Decimal("7")

    transfer = await client.post(
        "/api/v1/stock-transfers",
        headers=headers,
        json={
            "from_warehouse_id": ids["main"],
            "to_warehouse_id": dest_id,
            "lines": [{"product_id": product_id, "qty": "4"}],
        },
    )
    assert transfer.status_code == 201, transfer.text
    doc = transfer.json()["data"]
    rejected = await _post_document(
        client, headers, f"/api/v1/stock-transfers/{doc['id']}/post", doc["version"]
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error"]["code"] == "INVENTORY_INSUFFICIENT_STOCK"
    assert Decimal(rejected.json()["error"]["details"]["available_qty"]) == Decimal("3")


@pytest.mark.asyncio
async def test_count_adjustment_computes_delta_from_booked(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    opening = await _create_adjustment(
        client, headers, warehouse_id=ids["main"], product_id=product_id, qty_delta="10"
    )
    opening_doc = opening["body"]["data"]
    posted_open = await _post_document(
        client,
        headers,
        f"/api/v1/stock-adjustments/{opening_doc['id']}/post",
        opening_doc["version"],
    )
    assert posted_open.status_code == 200, posted_open.text

    count = await _create_adjustment(
        client,
        headers,
        warehouse_id=ids["main"],
        product_id=product_id,
        reason="COUNT",
        qty_delta=None,
        qty_counted="7",
    )
    assert count["status_code"] == 201, count["text"]
    doc = count["body"]["data"]
    posted = await _post_document(
        client, headers, f"/api/v1/stock-adjustments/{doc['id']}/post", doc["version"]
    )
    assert posted.status_code == 200, posted.text
    line = posted.json()["data"]["lines"][0]
    assert Decimal(line["qty_counted"]) == Decimal("7")
    assert Decimal(line["qty_booked"]) == Decimal("10")
    assert Decimal(line["qty_delta"]) == Decimal("-3")
    stock = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    assert Decimal(stock.json()["data"][0]["qty_on_hand"]) == Decimal("7")


@pytest.mark.asyncio
async def test_period_lock_rejects_dated_post(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await client.post(
        "/api/v1/stock-adjustments",
        headers=headers,
        json={
            "warehouse_id": ids["main"],
            "reason": "OPENING_STOCK",
            "document_date": "2020-01-15",
            "lines": [{"product_id": product_id, "qty_delta": "5"}],
        },
    )
    assert created.status_code == 201, created.text
    doc = created.json()["data"]

    async with async_session_factory() as session, transaction(session):
        tenant = await session.get(Tenant, UUID(tenant_id))
        assert tenant is not None
        tenant.lock_date = date(2024, 12, 31)

    rejected = await _post_document(
        client, headers, f"/api/v1/stock-adjustments/{doc['id']}/post", doc["version"]
    )
    assert rejected.status_code == 409, rejected.text
    error = rejected.json()["error"]
    assert error["code"] == "PERIOD_LOCKED"
    assert error["details"]["document_date"] == "2020-01-15"
    assert error["details"]["lock_date"] == "2024-12-31"


@pytest.mark.asyncio
async def test_untracked_and_service_products_rejected(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    untracked = await _create_product(client, headers, ids, track_inventory=False)
    service = await _create_product(client, headers, ids, track_inventory=True, item_type="SERVICE")
    untracked_adj = await _create_adjustment(
        client, headers, warehouse_id=ids["main"], product_id=untracked
    )
    assert untracked_adj["status_code"] == 422, untracked_adj["text"]
    service_adj = await _create_adjustment(
        client, headers, warehouse_id=ids["main"], product_id=service
    )
    assert service_adj["status_code"] == 422, service_adj["text"]


@pytest.mark.asyncio
async def test_cannot_turn_off_track_inventory_after_movements(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_adjustment(
        client, headers, warehouse_id=ids["main"], product_id=product_id
    )
    doc = created["body"]["data"]
    posted = await _post_document(
        client, headers, f"/api/v1/stock-adjustments/{doc['id']}/post", doc["version"]
    )
    assert posted.status_code == 200, posted.text
    updated = await client.patch(
        f"/api/v1/products/{product_id}",
        headers=headers,
        json={"track_inventory": False},
    )
    assert updated.status_code == 422, updated.text
    assert updated.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_post_requires_idempotency_key(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_adjustment(
        client, headers, warehouse_id=ids["main"], product_id=product_id
    )
    doc = created["body"]["data"]
    missing = await client.post(
        f"/api/v1/stock-adjustments/{doc['id']}/post",
        headers=_if_match(headers, doc["version"]),
    )
    assert missing.status_code == 422, missing.text


@pytest.mark.asyncio
async def test_transfer_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    ids = await _seeded(client, headers_a)
    dest_id = await _create_warehouse(client, headers_a)
    product_id = await _create_product(client, headers_a, ids)
    transfer = await client.post(
        "/api/v1/stock-transfers",
        headers=headers_a,
        json={
            "from_warehouse_id": ids["main"],
            "to_warehouse_id": dest_id,
            "lines": [{"product_id": product_id, "qty": "1"}],
        },
    )
    assert transfer.status_code == 201, transfer.text
    transfer_id = transfer.json()["data"]["id"]
    fetched = await client.get(f"/api/v1/stock-transfers/{transfer_id}", headers=headers_b)
    assert fetched.status_code == 404
    listed = await client.get("/api/v1/stock-transfers", headers=headers_b)
    assert listed.status_code == 200
    assert all(item["id"] != transfer_id for item in listed.json()["data"])


@pytest.mark.asyncio
async def test_reorder_patch_and_below_reorder_filter(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_adjustment(
        client, headers, warehouse_id=ids["main"], product_id=product_id, qty_delta="2"
    )
    doc = created["body"]["data"]
    posted = await _post_document(
        client, headers, f"/api/v1/stock-adjustments/{doc['id']}/post", doc["version"]
    )
    assert posted.status_code == 200, posted.text
    stock = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    balance_id = stock.json()["data"][0]["id"]
    updated = await client.patch(
        f"/api/v1/stock/{balance_id}/reorder",
        headers=headers,
        json={"reorder_level": "5", "reorder_qty": "20"},
    )
    assert updated.status_code == 200, updated.text
    assert Decimal(updated.json()["data"]["reorder_level"]) == Decimal("5")
    below = await client.get("/api/v1/stock?below_reorder=true", headers=headers)
    assert below.status_code == 200, below.text
    assert any(item["id"] == balance_id for item in below.json()["data"])


@pytest.mark.asyncio
async def test_list_extra_filters(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    suffix = uuid4().hex[:8]
    category = await client.post(
        "/api/v1/categories",
        headers=headers,
        json={"code": f"CAT-{suffix}", "name": f"Pipes {suffix}"},
    )
    assert category.status_code == 201, category.text
    category_id = category.json()["data"]["id"]
    other_category = await client.post(
        "/api/v1/categories",
        headers=headers,
        json={"code": f"OTH-{suffix}", "name": f"Other {suffix}"},
    )
    assert other_category.status_code == 201, other_category.text
    other_category_id = other_category.json()["data"]["id"]

    product_a = await _create_product(client, headers, ids, category_id=category_id)
    product_b = await _create_product(client, headers, ids, category_id=other_category_id)
    for product_id in (product_a, product_b):
        created = await _create_adjustment(
            client, headers, warehouse_id=ids["main"], product_id=product_id, qty_delta="5"
        )
        assert created["status_code"] == 201, created["text"]
        doc = created["body"]["data"]
        posted = await _post_document(
            client, headers, f"/api/v1/stock-adjustments/{doc['id']}/post", doc["version"]
        )
        assert posted.status_code == 200, posted.text

    by_category = await client.get(f"/api/v1/stock?category_id={category_id}", headers=headers)
    assert by_category.status_code == 200, by_category.text
    category_rows = by_category.json()["data"]
    assert [row["product_id"] for row in category_rows] == [product_a]

    by_warehouse_search = await client.get("/api/v1/stock?search=MAIN", headers=headers)
    assert by_warehouse_search.status_code == 200, by_warehouse_search.text
    assert {row["product_id"] for row in by_warehouse_search.json()["data"]} == {
        product_a,
        product_b,
    }

    sku = (await client.get(f"/api/v1/products/{product_a}", headers=headers)).json()["data"]["sku"]
    by_product_search = await client.get(f"/api/v1/stock?search={sku}", headers=headers)
    assert [row["product_id"] for row in by_product_search.json()["data"]] == [product_a]

    by_line = await client.get(f"/api/v1/stock-adjustments?product_id={product_a}", headers=headers)
    assert by_line.status_code == 200, by_line.text
    adjustment_ids = [row["id"] for row in by_line.json()["data"]]
    assert len(adjustment_ids) == 1
    assert by_line.json()["data"][0]["lines"][0]["product_id"] == product_a

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    future = await client.get(
        f"/api/v1/stock-adjustments?document_date_from={tomorrow}", headers=headers
    )
    assert future.status_code == 200, future.text
    assert future.json()["data"] == []

    movements = await client.get(
        f"/api/v1/stock-movements?category_id={category_id}&search={sku}",
        headers=headers,
    )
    assert movements.status_code == 200, movements.text
    movement_rows = movements.json()["data"]
    assert movement_rows
    assert all(row["product_id"] == product_a for row in movement_rows)

    dest_id = await _create_warehouse(client, headers)
    transfer = await client.post(
        "/api/v1/stock-transfers",
        headers=headers,
        json={
            "from_warehouse_id": ids["main"],
            "to_warehouse_id": dest_id,
            "lines": [{"product_id": product_a, "qty": "1"}],
        },
    )
    assert transfer.status_code == 201, transfer.text
    other_transfer = await client.post(
        "/api/v1/stock-transfers",
        headers=headers,
        json={
            "from_warehouse_id": ids["main"],
            "to_warehouse_id": dest_id,
            "lines": [{"product_id": product_b, "qty": "1"}],
        },
    )
    assert other_transfer.status_code == 201, other_transfer.text
    listed_transfers = await client.get(
        f"/api/v1/stock-transfers?product_id={product_a}", headers=headers
    )
    assert listed_transfers.status_code == 200, listed_transfers.text
    assert [row["id"] for row in listed_transfers.json()["data"]] == [transfer.json()["data"]["id"]]

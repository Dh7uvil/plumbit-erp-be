"""API tests for purchase orders: VAT, purchase rates, isolation, and issue."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.db.session import async_session_factory
from app.inventory_management.stock.models import StockMovement
from tests.conftest import login_headers, provision_admin


async def _seeded_ids(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    currencies = await client.get("/api/v1/currencies?is_base=true", headers=headers)
    assert currencies.status_code == 200, currencies.text
    aed = currencies.json()["data"][0]
    taxes = await client.get("/api/v1/taxes?page_size=100", headers=headers)
    assert taxes.status_code == 200, taxes.text
    by_category = {item["tax_category"]: item for item in taxes.json()["data"]}
    units = await client.get("/api/v1/units?page_size=100", headers=headers)
    assert units.status_code == 200, units.text
    pcs = next(item for item in units.json()["data"] if item["code"] == "PCS")
    return {
        "aed": aed["id"],
        "standard_tax": by_category["STANDARD"]["id"],
        "pcs": pcs["id"],
    }


async def _create_supplier(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    tax_treatment: str = "REGISTERED",
    trn: str | None = "100000000000003",
    shipping_state: str | None = "DUBAI",
    shipping_country_code: str = "AE",
) -> str:
    suffix = uuid4().hex[:8]
    payload: dict[str, object] = {
        "name": f"Supplier {suffix}",
        "code": f"S-{suffix}",
        "tax_treatment": tax_treatment,
        "trn": trn,
        "shipping_address": {
            "address_line_1": "Factory 1",
            "city": "Dubai" if shipping_country_code == "AE" else "London",
            "state": shipping_state,
            "country_code": shipping_country_code,
            "country": "United Arab Emirates"
            if shipping_country_code == "AE"
            else "United Kingdom",
        },
        "billing_address": {
            "address_line_1": "Accounts 1",
            "city": "Dubai" if shipping_country_code == "AE" else "London",
            "state": shipping_state,
            "country_code": shipping_country_code,
            "country": "United Arab Emirates"
            if shipping_country_code == "AE"
            else "United Kingdom",
        },
    }
    response = await client.post("/api/v1/suppliers", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


async def _create_product(
    client: AsyncClient,
    headers: dict[str, str],
    ids: dict[str, str],
    *,
    purchase_rate: str = "80.0000",
    purchase_description: str = "Supplier copper pipe",
) -> str:
    suffix = uuid4().hex[:8]
    response = await client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "sku": f"SKU-{suffix}",
            "name": f"Pipe {suffix}",
            "sales_description": "Copper pipe",
            "purchase_description": purchase_description,
            "unit_id": ids["pcs"],
            "selling_rate": "100.0000",
            "purchase_rate": purchase_rate,
            "tax_id": ids["standard_tax"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


async def _create_order(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    supplier_id: str,
    product_id: str,
    quantity: str = "2",
    rate: str | None = None,
) -> dict[str, object]:
    line: dict[str, object] = {"product_id": product_id, "quantity": quantity}
    if rate is not None:
        line["rate"] = rate
    response = await client.post(
        "/api/v1/purchase-orders",
        headers=headers,
        json={"supplier_id": supplier_id, "lines": [line]},
    )
    return {"status_code": response.status_code, "body": response.json(), "text": response.text}


def _if_match(headers: dict[str, str], version: object) -> dict[str, str]:
    return {**headers, "If-Match": str(version)}


@pytest.mark.asyncio
async def test_purchase_rate_defaults_onto_line(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    supplier_id = await _create_supplier(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_order(client, headers, supplier_id=supplier_id, product_id=product_id)
    assert created["status_code"] == 201, created["text"]
    data = created["body"]["data"]
    assert Decimal(data["lines"][0]["rate"]) == Decimal("80.0000")
    assert data["lines"][0]["description"] == "Supplier copper pipe"
    assert Decimal(data["subtotal"]) == Decimal("160.0000")
    assert Decimal(data["tax_amount"]) == Decimal("8.0000")
    assert Decimal(data["grand_total"]) == Decimal("168.0000")
    assert data["receipt_status"] == "NOT_RECEIVED"
    assert {"issue", "submit", "cancel", "clone", "delete"}.issubset(data["available_actions"])


@pytest.mark.asyncio
async def test_foreign_supplier_is_zero_rated(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    supplier_id = await _create_supplier(
        client,
        headers,
        tax_treatment="UNREGISTERED",
        trn=None,
        shipping_state=None,
        shipping_country_code="GB",
    )
    product_id = await _create_product(client, headers, ids)
    created = await _create_order(client, headers, supplier_id=supplier_id, product_id=product_id)
    assert created["status_code"] == 201, created["text"]
    data = created["body"]["data"]
    assert data["place_of_supply"] == "OUTSIDE_UAE"
    assert Decimal(data["tax_amount"]) == Decimal("0.0000")
    assert Decimal(data["grand_total"]) == Decimal("160.0000")


@pytest.mark.asyncio
async def test_issue_writes_no_stock_movements(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    supplier_id = await _create_supplier(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_order(client, headers, supplier_id=supplier_id, product_id=product_id)
    order_id = created["body"]["data"]["id"]
    issued = await client.post(
        f"/api/v1/purchase-orders/{order_id}/issue",
        headers=_if_match(headers, created["body"]["data"]["version"]),
    )
    assert issued.status_code == 200, issued.text
    assert issued.json()["data"]["status"] == "ISSUED"

    async with async_session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(StockMovement)
            .where(StockMovement.tenant_id == UUID(tenant_id))
        )
    assert int(count or 0) == 0


@pytest.mark.asyncio
async def test_stale_version_is_document_stale(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    supplier_id = await _create_supplier(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_order(client, headers, supplier_id=supplier_id, product_id=product_id)
    order_id = created["body"]["data"]["id"]
    stale = created["body"]["data"]["version"]
    first = await client.post(
        f"/api/v1/purchase-orders/{order_id}/submit", headers=_if_match(headers, stale)
    )
    assert first.status_code == 200, first.text
    retry = await client.post(
        f"/api/v1/purchase-orders/{order_id}/submit", headers=_if_match(headers, stale)
    )
    assert retry.status_code == 409, retry.text
    assert retry.json()["error"]["code"] == "DOCUMENT_STALE"


@pytest.mark.asyncio
async def test_purchase_order_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    ids_a = await _seeded_ids(client, headers_a)
    supplier_id = await _create_supplier(client, headers_a)
    product_id = await _create_product(client, headers_a, ids_a)
    created = await _create_order(client, headers_a, supplier_id=supplier_id, product_id=product_id)
    order_id = created["body"]["data"]["id"]
    fetched = await client.get(f"/api/v1/purchase-orders/{order_id}", headers=headers_b)
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    listed = await client.get("/api/v1/purchase-orders", headers=headers_b)
    assert listed.status_code == 200
    assert all(item["id"] != order_id for item in listed.json()["data"])

"""API tests for sales orders: VAT, isolation, workflow, and concurrency."""

from __future__ import annotations

import asyncio
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
        "exempt_tax": by_category["EXEMPT"]["id"],
        "pcs": pcs["id"],
    }


async def _create_customer(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    tax_treatment: str = "REGISTERED",
    trn: str | None = "100000000000003",
    shipping_state: str = "DUBAI",
    shipping_country_code: str = "AE",
) -> str:
    suffix = uuid4().hex[:8]
    payload: dict[str, object] = {
        "name": f"Customer {suffix}",
        "code": f"C-{suffix}",
        "tax_treatment": tax_treatment,
        "trn": trn,
        "shipping_address": {
            "address_line_1": "Warehouse 1",
            "city": "Dubai",
            "state": shipping_state,
            "country_code": shipping_country_code,
            "country": "United Arab Emirates" if shipping_country_code == "AE" else "Other",
        },
        "billing_address": {
            "address_line_1": "Office 1",
            "city": "Dubai",
            "state": "DUBAI",
            "country_code": "AE",
            "country": "United Arab Emirates",
        },
    }
    response = await client.post("/api/v1/customers", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


async def _create_product(
    client: AsyncClient,
    headers: dict[str, str],
    ids: dict[str, str],
    *,
    selling_rate: str = "100.0000",
    tax_id: str | None = None,
) -> str:
    suffix = uuid4().hex[:8]
    response = await client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "sku": f"SKU-{suffix}",
            "name": f"Pipe {suffix}",
            "sales_description": "Copper pipe",
            "unit_id": ids["pcs"],
            "selling_rate": selling_rate,
            "tax_id": tax_id or ids["standard_tax"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


async def _create_order(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    customer_id: str,
    product_id: str,
    quantity: str = "2",
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/sales-orders",
        headers=headers,
        json={
            "customer_id": customer_id,
            "lines": [{"product_id": product_id, "quantity": quantity}],
        },
    )
    return {"status_code": response.status_code, "body": response.json(), "text": response.text}


def _if_match(headers: dict[str, str], version: object) -> dict[str, str]:
    return {**headers, "If-Match": str(version)}


@pytest.mark.asyncio
async def test_registered_domestic_order_applies_five_percent_vat(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_order(client, headers, customer_id=customer_id, product_id=product_id)
    assert created["status_code"] == 201, created["text"]
    data = created["body"]["data"]
    assert Decimal(data["subtotal"]) == Decimal("200.0000")
    assert Decimal(data["tax_amount"]) == Decimal("10.0000")
    assert Decimal(data["grand_total"]) == Decimal("210.0000")
    assert data["fulfillment_status"] == "NOT_DELIVERED"
    assert data["billing_status"] == "NOT_INVOICED"
    assert data["is_posted"] is False
    assert data["document_date"] == data["order_date"]
    assert {"confirm", "submit", "cancel", "clone", "delete"}.issubset(data["available_actions"])


@pytest.mark.asyncio
async def test_export_order_is_zero_rated(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers, tax_treatment="EXPORT", trn=None)
    product_id = await _create_product(client, headers, ids)
    created = await _create_order(client, headers, customer_id=customer_id, product_id=product_id)
    assert created["status_code"] == 201, created["text"]
    assert Decimal(created["body"]["data"]["tax_amount"]) == Decimal("0.0000")


@pytest.mark.asyncio
async def test_confirm_from_draft_when_approval_not_required(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_order(client, headers, customer_id=customer_id, product_id=product_id)
    order_id = created["body"]["data"]["id"]
    confirmed = await client.post(
        f"/api/v1/sales-orders/{order_id}/confirm",
        headers=_if_match(headers, created["body"]["data"]["version"]),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["status"] == "CONFIRMED"
    assert confirmed.json()["data"]["confirmed_at"] is not None

    async with async_session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(StockMovement)
            .where(StockMovement.tenant_id == UUID(tenant_id))
        )
    assert int(count or 0) == 0


@pytest.mark.asyncio
async def test_confirmed_cannot_return_to_draft(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_order(client, headers, customer_id=customer_id, product_id=product_id)
    order_id = created["body"]["data"]["id"]
    confirmed = await client.post(
        f"/api/v1/sales-orders/{order_id}/confirm",
        headers=_if_match(headers, created["body"]["data"]["version"]),
    )
    reopened = await client.post(
        f"/api/v1/sales-orders/{order_id}/reopen",
        headers=_if_match(headers, confirmed.json()["data"]["version"]),
    )
    assert reopened.status_code == 409, reopened.text
    assert reopened.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


@pytest.mark.asyncio
async def test_stale_version_is_document_stale(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_order(client, headers, customer_id=customer_id, product_id=product_id)
    order_id = created["body"]["data"]["id"]
    stale = created["body"]["data"]["version"]
    first = await client.post(
        f"/api/v1/sales-orders/{order_id}/submit", headers=_if_match(headers, stale)
    )
    assert first.status_code == 200, first.text
    retry = await client.post(
        f"/api/v1/sales-orders/{order_id}/submit", headers=_if_match(headers, stale)
    )
    assert retry.status_code == 409, retry.text
    assert retry.json()["error"]["code"] == "DOCUMENT_STALE"


@pytest.mark.asyncio
async def test_duplicate_document_numbers_under_concurrency(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)

    async def create_one() -> str:
        created = await _create_order(
            client, headers, customer_id=customer_id, product_id=product_id
        )
        assert created["status_code"] == 201, created["text"]
        return str(created["body"]["data"]["document_number"])

    numbers = await asyncio.gather(*[create_one() for _ in range(5)])
    assert len(set(numbers)) == 5


@pytest.mark.asyncio
async def test_sales_order_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    ids_a = await _seeded_ids(client, headers_a)
    customer_id = await _create_customer(client, headers_a)
    product_id = await _create_product(client, headers_a, ids_a)
    created = await _create_order(client, headers_a, customer_id=customer_id, product_id=product_id)
    order_id = created["body"]["data"]["id"]
    fetched = await client.get(f"/api/v1/sales-orders/{order_id}", headers=headers_b)
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    listed = await client.get("/api/v1/sales-orders", headers=headers_b)
    assert listed.status_code == 200
    assert all(item["id"] != order_id for item in listed.json()["data"])


@pytest.mark.asyncio
async def test_available_actions_respect_permissions(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_order(client, headers, customer_id=customer_id, product_id=product_id)
    order_id = created["body"]["data"]["id"]
    permissions = await client.get("/api/v1/permissions?module=erp&page_size=100", headers=headers)
    codes = {item["code"]: item["id"] for item in permissions.json()["data"]}
    suffix = uuid4().hex[:8]
    role = await client.post(
        "/api/v1/roles",
        headers=headers,
        json={
            "name": f"Order reader {suffix}",
            "permission_ids": [codes["erp.sales_order.read"], codes["erp.sales_order.create"]],
        },
    )
    assert role.status_code == 201, role.text
    limited_email = f"reader-{suffix}@example.com"
    user = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "Order Reader",
            "email": limited_email,
            "password": "password12",
            "role_ids": [role.json()["data"]["id"]],
        },
    )
    assert user.status_code == 201, user.text
    limited_headers = await login_headers(client, tenant_id, limited_email, "password12")
    fetched = await client.get(f"/api/v1/sales-orders/{order_id}", headers=limited_headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["data"]["available_actions"] == ["clone"]


@pytest.mark.asyncio
async def test_confirmed_order_converts_to_proforma_invoice(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_order(
        client, headers, customer_id=customer_id, product_id=product_id, quantity="2"
    )
    assert created["status_code"] == 201, created["text"]
    order = created["body"]["data"]
    confirmed = await client.post(
        f"/api/v1/sales-orders/{order['id']}/confirm",
        headers=_if_match(headers, order["version"]),
    )
    assert confirmed.status_code == 200, confirmed.text
    confirmed_order = confirmed.json()["data"]
    assert "create_proforma" in confirmed_order["available_actions"]
    line_id = confirmed_order["lines"][0]["id"]

    partial = await client.post(
        f"/api/v1/sales-orders/{order['id']}/convert-to-proforma-invoice",
        headers=_if_match(headers, confirmed_order["version"]),
        json={"lines": [{"source_line_id": line_id, "quantity": "1"}]},
    )
    assert partial.status_code == 200, partial.text
    pfi = partial.json()["data"]
    assert pfi["source_sales_order_id"] == order["id"]
    assert Decimal(pfi["lines"][0]["quantity"]) == Decimal("1")

    refreshed = await client.get(f"/api/v1/sales-orders/{order['id']}", headers=headers)
    data = refreshed.json()["data"]
    assert Decimal(data["lines"][0]["qty_converted"]) == Decimal("1")
    assert data["quantity_progress"]["ordered"] is not None
    assert any(
        item["document_type"] == "PROFORMA_INVOICE" and item["relationship"] == "child"
        for item in data["related_documents"]
    )

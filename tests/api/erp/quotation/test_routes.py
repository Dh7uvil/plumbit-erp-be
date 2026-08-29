"""API tests for quotations: VAT, FX, status, isolation, and permissions."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _seeded_ids(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    currencies = await client.get("/api/v1/currencies?is_base=true", headers=headers)
    assert currencies.status_code == 200, currencies.text
    rows = currencies.json()["data"]
    assert len(rows) == 1
    aed = rows[0]
    assert aed["code"] == "AED"
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


async def _currency_id(client: AsyncClient, headers: dict[str, str], code: str) -> str:
    response = await client.get(f"/api/v1/currencies?search={code}", headers=headers)
    assert response.status_code == 200, response.text
    return next(item["id"] for item in response.json()["data"] if item["code"] == code)


async def _create_customer(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    tax_treatment: str = "REGISTERED",
    trn: str | None = "100000000000003",
    currency_id: str | None = None,
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
    if currency_id is not None:
        payload["currency_id"] = currency_id
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


async def _create_quote(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    customer_id: str,
    product_id: str,
    currency_id: str | None = None,
    quantity: str = "2",
    rate: str | None = None,
) -> dict[str, object]:
    line: dict[str, object] = {"product_id": product_id, "quantity": quantity}
    if rate is not None:
        line["rate"] = rate
    payload: dict[str, object] = {"customer_id": customer_id, "lines": [line]}
    if currency_id is not None:
        payload["currency_id"] = currency_id
    response = await client.post("/api/v1/quotations", headers=headers, json=payload)
    return {"status_code": response.status_code, "body": response.json(), "text": response.text}


@pytest.mark.asyncio
async def test_registered_domestic_quote_applies_five_percent_vat(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    assert created["status_code"] == 201, created["text"]
    data = created["body"]["data"]
    assert Decimal(data["subtotal"]) == Decimal("200.0000")
    assert Decimal(data["tax_amount"]) == Decimal("10.0000")
    assert Decimal(data["grand_total"]) == Decimal("210.0000")
    assert Decimal(data["exchange_rate"]) == Decimal("1")
    assert Decimal(data["lines"][0]["tax_rate"]) == Decimal("5")


@pytest.mark.asyncio
async def test_export_quote_is_zero_rated(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers, tax_treatment="EXPORT", trn=None)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    assert created["status_code"] == 201, created["text"]
    data = created["body"]["data"]
    assert Decimal(data["tax_amount"]) == Decimal("0.0000")
    assert Decimal(data["grand_total"]) == Decimal("200.0000")


@pytest.mark.asyncio
async def test_exempt_item_is_zero_vat_for_registered_domestic(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids, tax_id=ids["exempt_tax"])
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    assert created["status_code"] == 201, created["text"]
    assert Decimal(created["body"]["data"]["tax_amount"]) == Decimal("0.0000")


@pytest.mark.asyncio
async def test_missing_org_rate_rejects_foreign_currency_quote(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    usd_id = await _currency_id(client, headers, "USD")
    customer_id = await _create_customer(client, headers, currency_id=usd_id)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(
        client,
        headers,
        customer_id=customer_id,
        product_id=product_id,
        currency_id=usd_id,
    )
    assert created["status_code"] == 404, created["text"]
    assert created["body"]["error"]["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_fx_snapshot_unchanged_after_later_rate_update(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    usd_id = await _currency_id(client, headers, "USD")
    saved = await client.put(
        "/api/v1/exchange-rates",
        headers=headers,
        json={"currency_id": usd_id, "rate_to_base": "3.6725"},
    )
    assert saved.status_code == 200, saved.text
    customer_id = await _create_customer(client, headers, currency_id=usd_id)
    product_id = await _create_product(client, headers, ids, selling_rate="10.0000")
    created = await _create_quote(
        client, headers, customer_id=customer_id, product_id=product_id, currency_id=usd_id
    )
    assert created["status_code"] == 201, created["text"]
    quote = created["body"]["data"]
    assert Decimal(quote["exchange_rate"]) == Decimal("3.672500")
    original_base = Decimal(quote["base_amount"])
    updated = await client.put(
        "/api/v1/exchange-rates",
        headers=headers,
        json={"currency_id": usd_id, "rate_to_base": "4.0000"},
    )
    assert updated.status_code == 200, updated.text
    fetched = await client.get(f"/api/v1/quotations/{quote['id']}", headers=headers)
    assert fetched.status_code == 200, fetched.text
    assert Decimal(fetched.json()["data"]["exchange_rate"]) == Decimal("3.672500")
    assert Decimal(fetched.json()["data"]["base_amount"]) == original_base


@pytest.mark.asyncio
async def test_approve_then_send_happy_path(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    quote_id = created["body"]["data"]["id"]
    submitted = await client.post(f"/api/v1/quotations/{quote_id}/submit", headers=headers)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["data"]["status"] == "PENDING_APPROVAL"
    approved = await client.post(f"/api/v1/quotations/{quote_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    sent = await client.post(f"/api/v1/quotations/{quote_id}/send", headers=headers)
    assert sent.status_code == 200, sent.text
    assert sent.json()["data"]["status"] == "SENT"


@pytest.mark.asyncio
async def test_invalid_status_transition_from_accepted_to_draft(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    quote_id = created["body"]["data"]["id"]
    await client.post(f"/api/v1/quotations/{quote_id}/submit", headers=headers)
    await client.post(f"/api/v1/quotations/{quote_id}/approve", headers=headers)
    await client.post(f"/api/v1/quotations/{quote_id}/send", headers=headers)
    accepted = await client.post(f"/api/v1/quotations/{quote_id}/accept", headers=headers)
    assert accepted.status_code == 200, accepted.text
    reopened = await client.post(f"/api/v1/quotations/{quote_id}/reopen", headers=headers)
    assert reopened.status_code == 409, reopened.text
    assert reopened.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


@pytest.mark.asyncio
async def test_send_from_draft_rejected_when_approval_required(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    quote_id = created["body"]["data"]["id"]
    sent = await client.post(f"/api/v1/quotations/{quote_id}/send", headers=headers)
    assert sent.status_code == 422, sent.text


@pytest.mark.asyncio
async def test_client_totals_are_ignored(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    response = await client.post(
        "/api/v1/quotations",
        headers=headers,
        json={
            "customer_id": customer_id,
            "grand_total": "1.0000",
            "lines": [{"product_id": product_id, "quantity": "2", "line_total": "1.00"}],
        },
    )
    assert response.status_code == 201, response.text
    assert Decimal(response.json()["data"]["grand_total"]) == Decimal("210.0000")
    assert Decimal(response.json()["data"]["lines"][0]["amount"]) == Decimal("200.0000")


@pytest.mark.asyncio
async def test_duplicate_quote_numbers_under_concurrency(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)

    async def create_one() -> str:
        created = await _create_quote(
            client, headers, customer_id=customer_id, product_id=product_id
        )
        assert created["status_code"] == 201, created["text"]
        return str(created["body"]["data"]["quote_number"])

    import asyncio

    numbers = await asyncio.gather(*[create_one() for _ in range(5)])
    assert len(set(numbers)) == 5


@pytest.mark.asyncio
async def test_quotation_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    ids_a = await _seeded_ids(client, headers_a)
    customer_id = await _create_customer(client, headers_a)
    product_id = await _create_product(client, headers_a, ids_a)
    created = await _create_quote(client, headers_a, customer_id=customer_id, product_id=product_id)
    quote_id = created["body"]["data"]["id"]
    fetched = await client.get(f"/api/v1/quotations/{quote_id}", headers=headers_b)
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_quotation_permission_denied(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    permissions = await client.get("/api/v1/permissions?page_size=100", headers=headers)
    permission_id = next(
        item["id"] for item in permissions.json()["data"] if item["code"] == "identity.user.read"
    )
    suffix = uuid4().hex[:8]
    role = await client.post(
        "/api/v1/roles",
        headers=headers,
        json={"name": f"Limited {suffix}", "permission_ids": [permission_id]},
    )
    assert role.status_code == 201, role.text
    limited_email = f"limited-{suffix}@example.com"
    user = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "Limited User",
            "email": limited_email,
            "password": "password12",
            "role_ids": [role.json()["data"]["id"]],
        },
    )
    assert user.status_code == 201, user.text
    limited_headers = await login_headers(client, tenant_id, limited_email, "password12")
    denied = await client.post(
        "/api/v1/quotations",
        headers=limited_headers,
        json={"customer_id": str(uuid4()), "lines": []},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_clone_creates_new_draft_number(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    quote_id = created["body"]["data"]["id"]
    cloned = await client.post(f"/api/v1/quotations/{quote_id}/clone", headers=headers)
    assert cloned.status_code == 200, cloned.text
    assert cloned.json()["data"]["status"] == "DRAFT"
    assert cloned.json()["data"]["quote_number"] != created["body"]["data"]["quote_number"]

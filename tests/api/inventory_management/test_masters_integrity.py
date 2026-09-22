"""Usage guards, active-master checks, price lists, TRN, and category cycles."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin, unique_trn


async def _seeded(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    currencies = await client.get("/api/v1/currencies?is_base=true", headers=headers)
    assert currencies.status_code == 200, currencies.text
    aed = currencies.json()["data"][0]
    usd = await client.get("/api/v1/currencies?search=USD", headers=headers)
    usd_id = next(item["id"] for item in usd.json()["data"] if item["code"] == "USD")
    taxes = await client.get("/api/v1/taxes?page_size=100", headers=headers)
    by_category = {item["tax_category"]: item for item in taxes.json()["data"]}
    units = await client.get("/api/v1/units?page_size=100", headers=headers)
    pcs = next(item for item in units.json()["data"] if item["code"] == "PCS")
    return {
        "aed": aed["id"],
        "usd": usd_id,
        "standard_tax": by_category["STANDARD"]["id"],
        "pcs": pcs["id"],
    }


async def _create_product(
    client: AsyncClient,
    headers: dict[str, str],
    ids: dict[str, str],
    *,
    tax_id: str | None = None,
) -> str:
    suffix = uuid4().hex[:8]
    created = await client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "sku": f"SKU-{suffix}",
            "name": f"Pipe {suffix}",
            "unit_id": ids["pcs"],
            "selling_rate": "100.0000",
            "tax_id": tax_id or ids["standard_tax"],
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


async def _create_customer(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    currency_id: str,
    trn: str | None = None,
    tax_treatment: str = "REGISTERED",
    default_price_list_id: str | None = None,
) -> str:
    suffix = uuid4().hex[:8]
    resolved_trn = trn
    if resolved_trn is None and tax_treatment == "REGISTERED":
        resolved_trn = f"{int(uuid4().int % (10**15 - 1)) + 1:015d}"
    payload: dict[str, object] = {
        "name": f"Customer {suffix}",
        "tax_treatment": tax_treatment,
        "trn": resolved_trn,
        "currency_id": currency_id,
        "shipping_address": {
            "address_line_1": "Warehouse 1",
            "city": "Dubai",
            "state": "DUBAI",
            "country_code": "AE",
            "country": "United Arab Emirates",
        },
        "billing_address": {
            "address_line_1": "Office 1",
            "city": "Dubai",
            "state": "DUBAI",
            "country_code": "AE",
            "country": "United Arab Emirates",
        },
    }
    if default_price_list_id is not None:
        payload["default_price_list_id"] = default_price_list_id
    created = await client.post("/api/v1/customers", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


@pytest.mark.asyncio
async def test_cannot_delete_tax_referenced_by_product(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    await _create_product(client, headers, ids)
    deleted = await client.delete(f"/api/v1/taxes/{ids['standard_tax']}", headers=headers)
    assert deleted.status_code == 422, deleted.text
    assert "referenced" in deleted.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_inactive_product_rejected_on_new_quotation(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    deactivated = await client.patch(
        f"/api/v1/products/{product_id}",
        headers=headers,
        json={"is_active": False},
    )
    assert deactivated.status_code == 200, deactivated.text
    customer_id = await _create_customer(client, headers, currency_id=ids["aed"])
    quote = await client.post(
        "/api/v1/quotations",
        headers=headers,
        json={
            "customer_id": customer_id,
            "lines": [{"product_id": product_id, "quantity": "1"}],
        },
    )
    assert quote.status_code == 422, quote.text
    assert "inactive" in quote.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_inactive_tax_rejected_on_new_quotation_line(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    extra = await client.post(
        "/api/v1/taxes",
        headers=headers,
        json={"name": f"Extra {uuid4().hex[:6]}", "tax_category": "STANDARD", "rate": "5"},
    )
    assert extra.status_code == 201, extra.text
    tax_id = extra.json()["data"]["id"]
    deactivated = await client.patch(
        f"/api/v1/taxes/{tax_id}",
        headers=headers,
        json={"is_active": False},
    )
    assert deactivated.status_code == 200, deactivated.text
    product_id = await _create_product(client, headers, ids)
    customer_id = await _create_customer(client, headers, currency_id=ids["aed"])
    quote = await client.post(
        "/api/v1/quotations",
        headers=headers,
        json={
            "customer_id": customer_id,
            "lines": [{"product_id": product_id, "quantity": "1", "tax_id": tax_id}],
        },
    )
    assert quote.status_code == 422, quote.text
    assert "inactive" in quote.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_price_list_item_can_be_readded_after_soft_delete(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await client.post(
        "/api/v1/price-lists",
        headers=headers,
        json={
            "name": f"Custom {uuid4().hex[:6]}",
            "currency_id": ids["aed"],
            "list_type": "CUSTOM_RATES",
        },
    )
    assert created.status_code == 201, created.text
    price_list_id = created.json()["data"]["id"]
    added = await client.put(
        f"/api/v1/price-lists/{price_list_id}/items",
        headers=headers,
        json={"product_id": product_id, "rate": "12.5000"},
    )
    assert added.status_code == 200, added.text
    deleted = await client.delete(
        f"/api/v1/price-lists/{price_list_id}/items/{product_id}",
        headers=headers,
    )
    assert deleted.status_code == 200, deleted.text
    readded = await client.put(
        f"/api/v1/price-lists/{price_list_id}/items",
        headers=headers,
        json={"product_id": product_id, "rate": "15.0000"},
    )
    assert readded.status_code == 200, readded.text
    assert readded.json()["data"]["rate"] == "15.0000"


@pytest.mark.asyncio
async def test_price_list_currency_must_match_document_currency(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    price_list = await client.post(
        "/api/v1/price-lists",
        headers=headers,
        json={
            "name": f"USD list {uuid4().hex[:6]}",
            "currency_id": ids["usd"],
            "list_type": "PERCENT",
            "percent": "10",
        },
    )
    assert price_list.status_code == 201, price_list.text
    customer_id = await _create_customer(
        client,
        headers,
        currency_id=ids["aed"],
        default_price_list_id=price_list.json()["data"]["id"],
    )
    quote = await client.post(
        "/api/v1/quotations",
        headers=headers,
        json={
            "customer_id": customer_id,
            "lines": [{"product_id": product_id, "quantity": "1"}],
        },
    )
    assert quote.status_code == 422, quote.text
    assert "currency" in quote.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_registered_party_trn_is_unique(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    trn = f"1{uuid4().hex[:12]}"
    await _create_customer(client, headers, currency_id=ids["aed"], trn=trn)
    duplicate = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "name": f"Dup {uuid4().hex[:8]}",
            "tax_treatment": "REGISTERED",
            "trn": trn,
            "currency_id": ids["aed"],
        },
    )
    assert duplicate.status_code == 409, duplicate.text
    assert "trn" in duplicate.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_category_parent_cycle_is_rejected(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:6]
    parent = await client.post(
        "/api/v1/categories",
        headers=headers,
        json={"code": f"P-{suffix}", "name": f"Parent {suffix}"},
    )
    assert parent.status_code == 201, parent.text
    parent_id = parent.json()["data"]["id"]
    child = await client.post(
        "/api/v1/categories",
        headers=headers,
        json={"code": f"C-{suffix}", "name": f"Child {suffix}", "parent_id": parent_id},
    )
    assert child.status_code == 201, child.text
    cycled = await client.patch(
        f"/api/v1/categories/{parent_id}",
        headers=headers,
        json={"parent_id": child.json()["data"]["id"]},
    )
    assert cycled.status_code == 422, cycled.text
    assert "cycle" in cycled.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_inactive_document_sequence_cannot_allocate_and_next_number_cannot_drop(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    customer_id = await _create_customer(client, headers, currency_id=ids["aed"])
    created = await client.post(
        "/api/v1/quotations",
        headers=headers,
        json={
            "customer_id": customer_id,
            "lines": [{"product_id": product_id, "quantity": "1"}],
        },
    )
    assert created.status_code == 201, created.text
    listed = await client.get(
        "/api/v1/document-sequences?document_type=QUOTATION&page_size=100",
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    sequence = listed.json()["data"][0]
    assert sequence["next_number"] > 1
    lowered = await client.patch(
        f"/api/v1/document-sequences/{sequence['id']}",
        headers=headers,
        json={"next_number": 1},
    )
    assert lowered.status_code == 422, lowered.text
    assert "cannot be lowered" in lowered.json()["error"]["message"].lower()
    deactivated = await client.patch(
        f"/api/v1/document-sequences/{sequence['id']}",
        headers=headers,
        json={"is_active": False},
    )
    assert deactivated.status_code == 200, deactivated.text
    quote = await client.post(
        "/api/v1/quotations",
        headers=headers,
        json={
            "customer_id": customer_id,
            "lines": [{"product_id": product_id, "quantity": "1"}],
        },
    )
    assert quote.status_code == 422, quote.text
    assert "inactive" in quote.json()["error"]["message"].lower()

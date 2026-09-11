"""API tests for the supplier product catalog."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _create_supplier(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str | None = None,
    company_type: str | None = None,
    path: str = "/suppliers",
) -> dict[str, object]:
    suffix = uuid4().hex[:8]
    payload: dict[str, object] = {
        "name": name or f"Vendor {suffix}",
        "code": f"S-{suffix}",
        "tax_treatment": "UNREGISTERED",
    }
    if company_type is not None:
        payload["company_type"] = company_type
    created = await client.post(f"/api/v1{path}", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    return created.json()["data"]


async def _create_product(
    client: AsyncClient, headers: dict[str, str], *, purchase_rate: str = "80.0000"
) -> dict[str, object]:
    suffix = uuid4().hex[:8]
    units = await client.get("/api/v1/units?page_size=100", headers=headers)
    assert units.status_code == 200, units.text
    pcs = next(item for item in units.json()["data"] if item["code"] == "PCS")
    created = await client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "sku": f"SKU-{suffix}",
            "name": f"Pipe {suffix}",
            "purchase_rate": purchase_rate,
            "unit_id": pcs["id"],
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]


async def _create_catalog(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    supplier_id: str,
    supplier_sku: str,
    supplier_item_name: str = "Vendor pipe",
    product_id: str | None = None,
    price: str | None = None,
    currency_id: str | None = None,
    is_preferred: bool = False,
    is_preferred_supplier: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "supplier_id": supplier_id,
        "supplier_sku": supplier_sku,
        "supplier_item_name": supplier_item_name,
        "is_preferred": is_preferred,
        "is_preferred_supplier": is_preferred_supplier,
    }
    if product_id is not None:
        payload["product_id"] = product_id
    if price is not None:
        payload["price"] = price
    if currency_id is not None:
        payload["currency_id"] = currency_id
    created = await client.post("/api/v1/supplier-products", headers=headers, json=payload)
    return {"status_code": created.status_code, "body": created.json(), "text": created.text}


async def _permission_ids(
    client: AsyncClient, headers: dict[str, str], codes: tuple[str, ...]
) -> list[str]:
    found: dict[str, str] = {}
    searches = {code.split(".")[1] for code in codes}
    for search in searches:
        response = await client.get(
            f"/api/v1/permissions?search={search}&page_size=100", headers=headers
        )
        assert response.status_code == 200, response.text
        for item in response.json()["data"]:
            if item["code"] in codes:
                found[item["code"]] = item["id"]
    missing = set(codes) - set(found)
    assert not missing, missing
    return [found[code] for code in codes]


async def _user_headers(
    client: AsyncClient,
    admin_headers: dict[str, str],
    tenant_id: str,
    *,
    codes: tuple[str, ...],
) -> dict[str, str]:
    suffix = uuid4().hex[:8]
    email = f"limited-{suffix}@example.com"
    permission_ids = await _permission_ids(client, admin_headers, codes)
    role = await client.post(
        "/api/v1/roles",
        headers=admin_headers,
        json={"name": f"Limited {suffix}", "permission_ids": permission_ids},
    )
    assert role.status_code == 201, role.text
    user = await client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "name": "Limited User",
            "email": email,
            "password": "password12",
            "role_ids": [role.json()["data"]["id"]],
        },
    )
    assert user.status_code == 201, user.text
    return await login_headers(client, tenant_id, email, "password12")


@pytest.mark.asyncio
async def test_create_mapped_catalog_row(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    supplier = await _create_supplier(client, headers)
    product = await _create_product(client, headers)
    created = await _create_catalog(
        client,
        headers,
        supplier_id=str(supplier["id"]),
        supplier_sku="789",
        product_id=str(product["id"]),
        price="12.5000",
    )
    assert created["status_code"] == 201, created["text"]
    data = created["body"]["data"]
    assert data["supplier_sku"] == "789"
    assert data["is_mapped"] is True
    assert data["product_id"] == product["id"]
    assert data["product_sku"] == product["sku"]
    assert data["supplier_name"] == supplier["name"]
    assert data["currency_id"] == supplier["currency_id"]
    assert Decimal(data["price"]) == Decimal("12.5000")
    assert data["price_updated_at"] is not None


@pytest.mark.asyncio
async def test_customer_company_type_is_rejected(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    customer = await _create_supplier(client, headers, path="/customers")
    created = await _create_catalog(
        client,
        headers,
        supplier_id=str(customer["id"]),
        supplier_sku="CUST-1",
    )
    assert created["status_code"] == 404, created["text"]
    assert created["body"]["error"]["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_both_company_type_is_accepted(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    party = await _create_supplier(client, headers, path="/customers", company_type="BOTH")
    created = await _create_catalog(
        client,
        headers,
        supplier_id=str(party["id"]),
        supplier_sku="BOTH-1",
    )
    assert created["status_code"] == 201, created["text"]
    assert created["body"]["data"]["supplier_id"] == party["id"]


@pytest.mark.asyncio
async def test_duplicate_and_normalized_sku_collision(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    supplier = await _create_supplier(client, headers)
    first = await _create_catalog(
        client, headers, supplier_id=str(supplier["id"]), supplier_sku="abc-1"
    )
    assert first["status_code"] == 201, first["text"]
    duplicate = await _create_catalog(
        client, headers, supplier_id=str(supplier["id"]), supplier_sku="abc-1"
    )
    assert duplicate["status_code"] == 422, duplicate["text"]
    assert duplicate["body"]["error"]["code"] == "VALIDATION_ERROR"
    assert "abc-1" in duplicate["body"]["error"]["message"]
    collision = await _create_catalog(
        client, headers, supplier_id=str(supplier["id"]), supplier_sku=" ABC-1 "
    )
    assert collision["status_code"] == 422, collision["text"]
    assert collision["body"]["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_mapped_filter_and_unmapped_resolve(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    supplier = await _create_supplier(client, headers)
    product = await _create_product(client, headers)
    unmapped = await _create_catalog(
        client, headers, supplier_id=str(supplier["id"]), supplier_sku="U-1"
    )
    mapped = await _create_catalog(
        client,
        headers,
        supplier_id=str(supplier["id"]),
        supplier_sku="M-1",
        product_id=str(product["id"]),
    )
    assert unmapped["status_code"] == 201, unmapped["text"]
    assert mapped["status_code"] == 201, mapped["text"]
    listed = await client.get(
        "/api/v1/supplier-products",
        headers=headers,
        params={"mapped": "false", "supplier_id": supplier["id"]},
    )
    assert listed.status_code == 200, listed.text
    ids = {item["id"] for item in listed.json()["data"]}
    assert unmapped["body"]["data"]["id"] in ids
    assert mapped["body"]["data"]["id"] not in ids


@pytest.mark.asyncio
async def test_link_unlink_and_activity(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    supplier = await _create_supplier(client, headers)
    product = await _create_product(client, headers)
    created = await _create_catalog(
        client, headers, supplier_id=str(supplier["id"]), supplier_sku="789"
    )
    assert created["status_code"] == 201, created["text"]
    row_id = created["body"]["data"]["id"]
    linked = await client.post(
        f"/api/v1/supplier-products/{row_id}/link",
        headers=headers,
        json={"product_id": product["id"]},
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["data"]["is_mapped"] is True
    assert linked.json()["data"]["product_id"] == product["id"]
    unlinked = await client.post(
        f"/api/v1/supplier-products/{row_id}/unlink",
        headers=headers,
    )
    assert unlinked.status_code == 200, unlinked.text
    assert unlinked.json()["data"]["is_mapped"] is False
    assert unlinked.json()["data"]["is_preferred"] is False
    activity = await client.get(
        "/api/v1/activity",
        headers=headers,
        params={"entity_type": "supplier_product", "entity_id": row_id},
    )
    assert activity.status_code == 200, activity.text
    actions = {item["action"] for item in activity.json()["data"]}
    assert {"CREATE", "LINK", "UNLINK"} <= actions


@pytest.mark.asyncio
async def test_resolve_statuses_and_batch(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    supplier = await _create_supplier(client, headers)
    product = await _create_product(client, headers)
    mapped = await _create_catalog(
        client,
        headers,
        supplier_id=str(supplier["id"]),
        supplier_sku="MAP-1",
        product_id=str(product["id"]),
    )
    unmapped = await _create_catalog(
        client, headers, supplier_id=str(supplier["id"]), supplier_sku="UN-1"
    )
    assert mapped["status_code"] == 201, mapped["text"]
    assert unmapped["status_code"] == 201, unmapped["text"]
    mapped_resolve = await client.get(
        "/api/v1/supplier-products/resolve",
        headers=headers,
        params={"supplier_id": supplier["id"], "supplier_sku": "map-1"},
    )
    assert mapped_resolve.status_code == 200, mapped_resolve.text
    assert mapped_resolve.json()["data"]["status"] == "MAPPED"
    assert mapped_resolve.json()["data"]["product_id"] == product["id"]
    unmapped_resolve = await client.get(
        "/api/v1/supplier-products/resolve",
        headers=headers,
        params={"supplier_id": supplier["id"], "supplier_sku": "un-1 "},
    )
    assert unmapped_resolve.status_code == 200, unmapped_resolve.text
    assert unmapped_resolve.json()["data"]["status"] == "UNMAPPED"
    unknown = await client.get(
        "/api/v1/supplier-products/resolve",
        headers=headers,
        params={"supplier_id": supplier["id"], "supplier_sku": "NOPE"},
    )
    assert unknown.status_code == 200, unknown.text
    assert unknown.json()["data"]["status"] == "UNKNOWN_SKU"
    batch = await client.post(
        "/api/v1/supplier-products/resolve",
        headers=headers,
        json={
            "supplier_id": supplier["id"],
            "supplier_skus": ["MAP-1", "UN-1", "NOPE"],
        },
    )
    assert batch.status_code == 200, batch.text
    statuses = [item["status"] for item in batch.json()["data"]]
    assert statuses == ["MAPPED", "UNMAPPED", "UNKNOWN_SKU"]


@pytest.mark.asyncio
async def test_update_does_not_change_product_id(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    supplier = await _create_supplier(client, headers)
    product = await _create_product(client, headers)
    created = await _create_catalog(
        client,
        headers,
        supplier_id=str(supplier["id"]),
        supplier_sku="KEEP",
        product_id=str(product["id"]),
    )
    row_id = created["body"]["data"]["id"]
    patched = await client.patch(
        f"/api/v1/supplier-products/{row_id}",
        headers=headers,
        json={"product_id": str(uuid4()), "supplier_item_name": "Renamed"},
    )
    assert patched.status_code == 422, patched.text
    fetched = await client.get(f"/api/v1/supplier-products/{row_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["data"]["product_id"] == product["id"]
    renamed = await client.patch(
        f"/api/v1/supplier-products/{row_id}",
        headers=headers,
        json={"supplier_item_name": "Renamed"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["data"]["supplier_item_name"] == "Renamed"


@pytest.mark.asyncio
async def test_permission_gating(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    supplier = await _create_supplier(client, headers)
    product = await _create_product(client, headers)
    created = await _create_catalog(
        client, headers, supplier_id=str(supplier["id"]), supplier_sku="PERM"
    )
    assert created["status_code"] == 201, created["text"]
    row_id = created["body"]["data"]["id"]
    reader = await _user_headers(client, headers, tenant_id, codes=("purchase.supplier_product.read",))
    listed = await client.get("/api/v1/supplier-products", headers=reader)
    assert listed.status_code == 200, listed.text
    denied_create = await client.post(
        "/api/v1/supplier-products",
        headers=reader,
        json={
            "supplier_id": supplier["id"],
            "supplier_sku": "NOPE",
            "supplier_item_name": "Nope",
        },
    )
    assert denied_create.status_code == 403
    denied_link = await client.post(
        f"/api/v1/supplier-products/{row_id}/link",
        headers=reader,
        json={"product_id": product["id"]},
    )
    assert denied_link.status_code == 403


@pytest.mark.asyncio
async def test_supplier_product_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    supplier = await _create_supplier(client, headers_a)
    created = await _create_catalog(
        client, headers_a, supplier_id=str(supplier["id"]), supplier_sku="ISO"
    )
    assert created["status_code"] == 201, created["text"]
    row_id = created["body"]["data"]["id"]
    fetched = await client.get(f"/api/v1/supplier-products/{row_id}", headers=headers_b)
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    listed = await client.get("/api/v1/supplier-products", headers=headers_b)
    assert listed.status_code == 200
    assert all(item["id"] != row_id for item in listed.json()["data"])
    resolve_b = await client.get(
        "/api/v1/supplier-products/resolve",
        headers=headers_b,
        params={"supplier_id": supplier["id"], "supplier_sku": "ISO"},
    )
    assert resolve_b.status_code == 404

"""Product pieces_per_unit field."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _pcs_unit_id(client: AsyncClient, headers: dict[str, str]) -> str:
    units = await client.get("/api/v1/units?page_size=100", headers=headers)
    assert units.status_code == 200, units.text
    pcs = next(item for item in units.json()["data"] if item["code"] == "PCS")
    return pcs["id"]


@pytest.mark.asyncio
async def test_create_with_pieces_per_unit(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    unit_id = await _pcs_unit_id(client, headers)
    suffix = uuid4().hex[:8]
    created = await client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "sku": f"SKU-{suffix}",
            "name": f"Item {suffix}",
            "unit_id": unit_id,
            "pieces_per_unit": "12",
            "selling_rate": "10.0000",
        },
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert Decimal(data["pieces_per_unit"]) == Decimal("12")


@pytest.mark.asyncio
async def test_create_without_pieces_per_unit_is_null(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:8]
    created = await client.post(
        "/api/v1/products",
        headers=headers,
        json={"sku": f"SKU-{suffix}", "name": f"Item {suffix}", "selling_rate": "10.0000"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["pieces_per_unit"] is None


@pytest.mark.asyncio
async def test_create_rejects_non_positive_pieces_per_unit(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    unit_id = await _pcs_unit_id(client, headers)
    suffix = uuid4().hex[:8]
    for bad in ("0", "-1"):
        created = await client.post(
            "/api/v1/products",
            headers=headers,
            json={
                "sku": f"SKU-{suffix}-{bad}",
                "name": f"Item {suffix}",
                "unit_id": unit_id,
                "pieces_per_unit": bad,
                "selling_rate": "10.0000",
            },
        )
        assert created.status_code == 422, created.text


@pytest.mark.asyncio
async def test_clearing_unit_clears_pieces_per_unit(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    unit_id = await _pcs_unit_id(client, headers)
    suffix = uuid4().hex[:8]
    created = await client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "sku": f"SKU-{suffix}",
            "name": f"Item {suffix}",
            "unit_id": unit_id,
            "pieces_per_unit": "10",
            "selling_rate": "10.0000",
        },
    )
    assert created.status_code == 201, created.text
    product_id = created.json()["data"]["id"]
    updated = await client.patch(
        f"/api/v1/products/{product_id}",
        headers=headers,
        json={"unit_id": None},
    )
    assert updated.status_code == 200, updated.text
    data = updated.json()["data"]
    assert data["unit_id"] is None
    assert data["pieces_per_unit"] is None


@pytest.mark.asyncio
async def test_create_without_unit_ignores_pieces_per_unit(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:8]
    created = await client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "sku": f"SKU-{suffix}",
            "name": f"Item {suffix}",
            "pieces_per_unit": "12",
            "selling_rate": "10.0000",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["pieces_per_unit"] is None

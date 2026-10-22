"""Product secondary unit (unit 2) validation."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _unit_id(client: AsyncClient, headers: dict[str, str], code: str) -> str:
    units = await client.get("/api/v1/units?page_size=100", headers=headers)
    assert units.status_code == 200, units.text
    row = next(item for item in units.json()["data"] if item["code"] == code)
    return row["id"]


@pytest.mark.asyncio
async def test_create_rejects_unit2_without_factor(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    pcs_id = await _unit_id(client, headers, "PCS")
    box_id = await _unit_id(client, headers, "BOX")
    suffix = uuid4().hex[:8]
    created = await client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "sku": f"SKU-{suffix}",
            "name": f"Item {suffix}",
            "unit_id": pcs_id,
            "secondary_unit_id": box_id,
        },
    )
    assert created.status_code == 422, created.text


@pytest.mark.asyncio
async def test_create_rejects_unit2_same_as_base(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    pcs_id = await _unit_id(client, headers, "PCS")
    suffix = uuid4().hex[:8]
    created = await client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "sku": f"SKU-{suffix}",
            "name": f"Item {suffix}",
            "unit_id": pcs_id,
            "secondary_unit_id": pcs_id,
            "secondary_unit_factor": "10",
        },
    )
    assert created.status_code == 422, created.text


@pytest.mark.asyncio
async def test_update_name_ignores_incomplete_unit2_on_product(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    pcs_id = await _unit_id(client, headers, "PCS")
    box_id = await _unit_id(client, headers, "BOX")
    suffix = uuid4().hex[:8]
    created = await client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "sku": f"SKU-{suffix}",
            "name": f"Item {suffix}",
            "unit_id": pcs_id,
            "secondary_unit_id": box_id,
            "secondary_unit_factor": "10",
        },
    )
    assert created.status_code == 201, created.text
    product_id = created.json()["data"]["id"]

    updated = await client.patch(
        f"/api/v1/products/{product_id}",
        headers=headers,
        json={"name": f"Renamed {suffix}"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["name"] == f"Renamed {suffix}"

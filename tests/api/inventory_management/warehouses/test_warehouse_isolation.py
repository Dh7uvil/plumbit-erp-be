"""Tenant isolation and warehouse master rules."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_warehouse_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    suffix = uuid4().hex[:8]
    created = await client.post(
        "/api/v1/warehouses",
        headers=headers_a,
        json={"code": f"WH-{suffix}", "name": f"Warehouse {suffix}"},
    )
    assert created.status_code == 201, created.text
    warehouse_id = created.json()["data"]["id"]
    fetched = await client.get(f"/api/v1/warehouses/{warehouse_id}", headers=headers_b)
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    listed = await client.get("/api/v1/warehouses", headers=headers_b)
    assert listed.status_code == 200
    assert all(item["id"] != warehouse_id for item in listed.json()["data"])


@pytest.mark.asyncio
async def test_warehouse_duplicate_code_conflict(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:8]
    payload = {"code": f"WH-{suffix}", "name": f"Warehouse {suffix}"}
    created = await client.post("/api/v1/warehouses", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    duplicate = await client.post("/api/v1/warehouses", headers=headers, json=payload)
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["error"]["code"] == "DUPLICATE_RESOURCE"


@pytest.mark.asyncio
async def test_warehouse_second_default_unsets_first(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:8]
    first = await client.post(
        "/api/v1/warehouses",
        headers=headers,
        json={"code": f"WH-{suffix}-1", "name": f"First {suffix}"},
    )
    assert first.status_code == 201, first.text
    first_row = first.json()["data"]
    assert first_row["is_default"] is True
    second = await client.post(
        "/api/v1/warehouses",
        headers=headers,
        json={"code": f"WH-{suffix}-2", "name": f"Second {suffix}", "is_default": True},
    )
    assert second.status_code == 201, second.text
    assert second.json()["data"]["is_default"] is True
    fetched_first = await client.get(f"/api/v1/warehouses/{first_row['id']}", headers=headers)
    assert fetched_first.status_code == 200, fetched_first.text
    assert fetched_first.json()["data"]["is_default"] is False


@pytest.mark.asyncio
async def test_warehouse_list_returns_multiple_for_one_tenant(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:8]
    first = await client.post(
        "/api/v1/warehouses",
        headers=headers,
        json={"code": f"WH-{suffix}-1", "name": f"East {suffix}"},
    )
    assert first.status_code == 201, first.text
    created = await client.post(
        "/api/v1/warehouses",
        headers=headers,
        json={
            "code": f"WH-{suffix}-2",
            "name": f"West {suffix}",
            "phone": "04-123-4567",
            "address": {"city": "Dubai", "country": "UAE"},
        },
    )
    assert created.status_code == 201, created.text
    extra = created.json()["data"]
    assert extra["phone"] == "04-123-4567"
    assert extra["address"]["city"] == "Dubai"
    listed = await client.get("/api/v1/warehouses", headers=headers)
    assert listed.status_code == 200, listed.text
    ids = {item["id"] for item in listed.json()["data"]}
    assert first.json()["data"]["id"] in ids
    assert extra["id"] in ids
    assert listed.json()["meta"]["total"] >= 2

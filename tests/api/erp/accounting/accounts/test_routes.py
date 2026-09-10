"""API tests for chart of accounts: seed, tree, guards, and system roles."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.enums import AccountSystemRole
from tests.conftest import login_headers, provision_admin


async def _role_map(client: AsyncClient, headers: dict[str, str]) -> dict[str, dict[str, object]]:
    response = await client.get("/api/v1/accounts/system-roles", headers=headers)
    assert response.status_code == 200, response.text
    return {item["role"]: item for item in response.json()["data"]}


@pytest.mark.asyncio
async def test_fresh_tenant_has_mapped_uae_chart(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    listed = await client.get("/api/v1/accounts?page_size=100", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["meta"]["total"] > 0
    mapped = await _role_map(client, headers)
    assert set(mapped) == {role.value for role in AccountSystemRole}
    assert all(item["account_id"] is not None for item in mapped.values())
    tree = await client.get("/api/v1/accounts/tree", headers=headers)
    assert tree.status_code == 200, tree.text
    assert tree.json()["data"]


@pytest.mark.asyncio
async def test_group_account_cannot_be_deleted_while_it_has_children(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    listed = await client.get("/api/v1/accounts?is_group=true&page_size=100", headers=headers)
    assert listed.status_code == 200, listed.text
    group = next(item for item in listed.json()["data"] if item["code"] == "1000")
    deleted = await client.delete(f"/api/v1/accounts/{group['id']}", headers=headers)
    assert deleted.status_code == 422, deleted.text


@pytest.mark.asyncio
async def test_system_account_code_cannot_change(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    mapped = await _role_map(client, headers)
    cash_id = mapped["CASH_ON_HAND"]["account_id"]
    updated = await client.patch(
        f"/api/v1/accounts/{cash_id}",
        headers=headers,
        json={"code": "CASH-X"},
    )
    assert updated.status_code == 422, updated.text


@pytest.mark.asyncio
async def test_create_postable_child_under_matching_group(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    listed = await client.get("/api/v1/accounts?is_group=true&page_size=100", headers=headers)
    parent = next(item for item in listed.json()["data"] if item["code"] == "1000")
    suffix = uuid4().hex[:6]
    created = await client.post(
        "/api/v1/accounts",
        headers=headers,
        json={
            "code": f"14{suffix[:2]}",
            "name": f"Petty cash {suffix}",
            "account_type": "ASSET",
            "account_subtype": "CASH",
            "parent_id": parent["id"],
            "is_group": False,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["is_group"] is False
    assert created.json()["data"]["parent_id"] == parent["id"]

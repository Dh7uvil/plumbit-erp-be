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


@pytest.mark.asyncio
async def test_subtype_must_match_account_type(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    created = await client.post(
        "/api/v1/accounts",
        headers=headers,
        json={
            "code": f"99{uuid4().hex[:4]}",
            "name": "Invalid subtype",
            "account_type": "ASSET",
            "account_subtype": "ACCOUNTS_PAYABLE",
            "is_group": False,
        },
    )
    assert created.status_code == 422, created.text


@pytest.mark.asyncio
async def test_group_cannot_become_postable_while_it_has_children(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    listed = await client.get("/api/v1/accounts?is_group=true&page_size=100", headers=headers)
    assert listed.status_code == 200, listed.text
    group = next(item for item in listed.json()["data"] if item["code"] == "1000")
    detail = await client.get(f"/api/v1/accounts/{group['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["has_children"] is True
    updated = await client.patch(
        f"/api/v1/accounts/{group['id']}",
        headers=headers,
        json={"is_group": False},
    )
    assert updated.status_code == 422, updated.text


@pytest.mark.asyncio
async def test_postable_cannot_become_group_after_journal_lines(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    mapped = {item["role"]: item["account_id"] for item in roles.json()["data"]}
    bank = mapped["BANK"]
    cash = mapped["CASH_ON_HAND"]
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "entry_date": "2026-01-15",
            "lines": [
                {"account_id": bank, "debit": "10.00", "credit": "0"},
                {"account_id": cash, "debit": "0", "credit": "10.00"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    journal = created.json()["data"]
    posted = await client.post(
        f"/api/v1/journals/{journal['id']}/post",
        headers={**headers, "Idempotency-Key": uuid4().hex, "If-Match": str(journal["version"])},
    )
    assert posted.status_code == 200, posted.text
    detail = await client.get(f"/api/v1/accounts/{bank}", headers=headers)
    assert detail.json()["data"]["has_journal_lines"] is True
    updated = await client.patch(
        f"/api/v1/accounts/{bank}",
        headers=headers,
        json={"is_group": True},
    )
    assert updated.status_code == 422, updated.text

"""API tests for cost center master CRUD."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_cost_center_crud(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:6].upper()
    created = await client.post(
        "/api/v1/cost-centers",
        headers=headers,
        json={"name": f"Operations {suffix}", "code": f"CC{suffix}", "description": "Ops"},
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    assert row["code"] == f"CC{suffix}"
    assert row["is_active"] is True

    fetched = await client.get(f"/api/v1/cost-centers/{row['id']}", headers=headers)
    assert fetched.status_code == 200, fetched.text

    updated = await client.patch(
        f"/api/v1/cost-centers/{row['id']}",
        headers=headers,
        json={"description": "Updated"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["description"] == "Updated"

    deleted = await client.delete(f"/api/v1/cost-centers/{row['id']}", headers=headers)
    assert deleted.status_code == 200, deleted.text


@pytest.mark.asyncio
async def test_duplicate_cost_center_code_is_refused(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    code = f"DUP{uuid4().hex[:4].upper()}"
    first = await client.post(
        "/api/v1/cost-centers",
        headers=headers,
        json={"name": "First", "code": code},
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        "/api/v1/cost-centers",
        headers=headers,
        json={"name": "Second", "code": code},
    )
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "DUPLICATE_RESOURCE"

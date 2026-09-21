"""API tests for lost reason master CRUD."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_lost_reason_crud(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    created = await client.post(
        "/api/v1/lost-reasons",
        headers=headers,
        json={"name": f"Price {uuid4().hex[:6]}"},
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    deleted = await client.delete(f"/api/v1/lost-reasons/{row['id']}", headers=headers)
    assert deleted.status_code == 200, deleted.text


@pytest.mark.asyncio
async def test_duplicate_lost_reason_name_is_refused(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    name = f"Dup {uuid4().hex[:8]}"
    first = await client.post("/api/v1/lost-reasons", headers=headers, json={"name": name})
    assert first.status_code == 201, first.text
    second = await client.post("/api/v1/lost-reasons", headers=headers, json={"name": name})
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "DUPLICATE_RESOURCE"

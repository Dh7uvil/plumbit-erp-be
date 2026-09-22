"""API tests for charge type master."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_seeded_charge_types_list(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    listed = await client.get("/api/v1/charge-types?page_size=50", headers=headers)
    assert listed.status_code == 200, listed.text
    rows = listed.json()["data"]
    codes = {row["code"] for row in rows}
    assert "FREIGHT" in codes
    assert "BANK_CHARGES" in codes
    bank = next(row for row in rows if row["code"] == "BANK_CHARGES")
    assert bank["is_inventoriable"] is False


@pytest.mark.asyncio
async def test_charge_type_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    listed = await client.get("/api/v1/charge-types?page_size=1", headers=headers_a)
    charge_type_id = listed.json()["data"][0]["id"]
    cross = await client.get(f"/api/v1/charge-types/{charge_type_id}", headers=headers_b)
    assert cross.status_code == 404, cross.text


@pytest.mark.asyncio
async def test_update_charge_type_inventoriable_toggle(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    listed = await client.get("/api/v1/charge-types?search=INSURANCE", headers=headers)
    row = listed.json()["data"][0]
    updated = await client.patch(
        f"/api/v1/charge-types/{row['id']}",
        headers=headers,
        json={"is_inventoriable": False},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["is_inventoriable"] is False

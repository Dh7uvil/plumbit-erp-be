"""Charge type CRUD API."""

import pytest
from httpx import AsyncClient

from tests.api.erp.customer_payments.test_routes import _enable_books
from tests.conftest import login_headers, provision_admin


async def _expense_account(client: AsyncClient, headers: dict[str, str]) -> str:
    listed = await client.get("/api/v1/accounts", headers=headers)
    assert listed.status_code == 200, listed.text
    skip = {"ACCOUNTS_RECEIVABLE", "ACCOUNTS_PAYABLE", "CASH", "BANK", "STOCK"}
    for row in listed.json()["data"]:
        if row.get("is_group"):
            continue
        if row.get("account_subtype") in skip:
            continue
        return row["id"]
    raise AssertionError("expense account not found")


@pytest.mark.asyncio
async def test_create_charge_type(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    account_id = await _expense_account(client, headers)
    created = await client.post(
        "/api/v1/charge-types",
        headers=headers,
        json={
            "code": "TEST_FREIGHT",
            "name": "Test freight",
            "is_inventoriable": True,
            "default_account_id": account_id,
            "applies_to": "IMPORT",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()["data"]
    assert body["code"] == "TEST_FREIGHT"
    assert body["is_inventoriable"] is True

"""Blocked chart accounts cannot receive postings."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _accounts(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    assert roles.status_code == 200, roles.text
    return {item["role"]: item["account_id"] for item in roles.json()["data"]}


@pytest.mark.asyncio
async def test_journal_post_rejects_blocked_account(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    blocked_id = accounts["SALES_REVENUE"]
    patched = await client.patch(
        f"/api/v1/accounts/{blocked_id}",
        headers=headers,
        json={"is_blocked": True},
    )
    assert patched.status_code == 200, patched.text
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "lines": [
                {"account_id": accounts["CASH_ON_HAND"], "debit": "10.0000", "credit": "0"},
                {"account_id": blocked_id, "debit": "0", "credit": "10.0000"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    posted = await client.post(
        f"/api/v1/journals/{row['id']}/post",
        headers={**headers, "If-Match": str(row["version"]), "Idempotency-Key": "blk1"},
    )
    assert posted.status_code == 422, posted.text
    assert posted.json()["error"]["code"] == "ACCOUNT_NOT_POSTABLE"

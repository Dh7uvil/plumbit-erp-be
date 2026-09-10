"""Inventory documents post to the GL only after books_start_date is set."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.api.inventory_management.goods_receipts.test_routes import (
    _create_from_po,
    _idempotent,
    _issue_tracked_po,
    _post_grn,
)
from tests.conftest import login_headers, provision_admin


async def _enable_books(client: AsyncClient, headers: dict[str, str]) -> None:
    today = datetime.now(UTC).date().isoformat()
    updated = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"books_start_date": today},
    )
    assert updated.status_code == 200, updated.text


@pytest.mark.asyncio
async def test_grn_post_without_books_start_writes_no_journal(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ctx = await _issue_tracked_po(client, headers, quantity="4")
    created = await _create_from_po(client, headers, ctx["order"]["id"])
    posted = await _post_grn(
        client, headers, created["body"]["data"]["id"], created["body"]["data"]["version"]
    )
    assert posted.status_code == 200, posted.text
    journals = await client.get(
        "/api/v1/journals",
        headers=headers,
        params={"journal_type": "SYSTEM", "page_size": 50},
    )
    assert journals.status_code == 200, journals.text
    assert journals.json()["meta"]["total"] == 0


@pytest.mark.asyncio
async def test_grn_post_after_books_start_debits_inventory(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    mapped = {item["role"]: item["account_id"] for item in roles.json()["data"]}
    assert mapped["GOODS_RECEIVED_NOT_INVOICED"]
    ctx = await _issue_tracked_po(client, headers, quantity="4")
    created = await _create_from_po(client, headers, ctx["order"]["id"])
    posted = await _post_grn(
        client, headers, created["body"]["data"]["id"], created["body"]["data"]["version"]
    )
    assert posted.status_code == 200, posted.text
    journals = await client.get(
        "/api/v1/journals",
        headers=headers,
        params={"journal_type": "SYSTEM", "page_size": 50},
    )
    assert journals.status_code == 200, journals.text
    assert journals.json()["meta"]["total"] == 1
    entry = journals.json()["data"][0]
    detail = await client.get(f"/api/v1/journals/{entry['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    lines = detail.json()["data"]["lines"]
    by_account = {line["account_id"]: line for line in lines}
    inventory = by_account[mapped["INVENTORY"]]
    grni = by_account[mapped["GOODS_RECEIVED_NOT_INVOICED"]]
    assert Decimal(inventory["debit"]) > Decimal("0")
    assert Decimal(grni["credit"]) == Decimal(inventory["debit"])

    cancelled = await client.post(
        f"/api/v1/goods-receipts/{created['body']['data']['id']}/cancel",
        headers=_idempotent(headers, posted.json()["data"]["version"]),
        json={"reason": "Posted in error"},
    )
    assert cancelled.status_code == 200, cancelled.text
    journals_after = await client.get(
        "/api/v1/journals",
        headers=headers,
        params={"journal_type": "REVERSAL", "page_size": 50},
    )
    assert journals_after.status_code == 200, journals_after.text
    assert journals_after.json()["meta"]["total"] == 1

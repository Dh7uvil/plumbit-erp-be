"""Ledger master: party-linked and standalone AR/AP accounts."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _ap_parent_id(client: AsyncClient, headers: dict[str, str]) -> str | None:
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    assert roles.status_code == 200, roles.text
    ap_id = next(
        item["account_id"]
        for item in roles.json()["data"]
        if item["role"] == "ACCOUNTS_PAYABLE"
    )
    detail = await client.get(f"/api/v1/accounts/{ap_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    return detail.json()["data"]["parent_id"]


@pytest.mark.asyncio
async def test_create_standalone_ap_ledger(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    parent_id = await _ap_parent_id(client, headers)
    suffix = uuid4().hex[:6]
    created = await client.post(
        "/api/v1/accounts",
        headers=headers,
        json={
            "code": f"AP{suffix}",
            "name": f"Direct expenses payable {suffix}",
            "account_type": "LIABILITY",
            "account_subtype": "ACCOUNTS_PAYABLE",
            "parent_id": parent_id,
            "is_group": False,
            "is_standalone_ledger": True,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()["data"]
    assert body["is_standalone_ledger"] is True
    assert body["linked_party_id"] is None


@pytest.mark.asyncio
async def test_create_ap_with_new_supplier_link(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    parent_id = await _ap_parent_id(client, headers)
    suffix = uuid4().hex[:6]
    created = await client.post(
        "/api/v1/accounts",
        headers=headers,
        json={
            "code": f"SP{suffix}",
            "name": f"Supplier ledger {suffix}",
            "account_type": "LIABILITY",
            "account_subtype": "ACCOUNTS_PAYABLE",
            "parent_id": parent_id,
            "is_group": False,
            "party_link": {
                "mode": "new",
                "party_type": "SUPPLIER",
                "name": f"Linked supplier {suffix}",
            },
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()["data"]
    assert body["linked_party_name"] == f"Linked supplier {suffix}"
    assert body["linked_party_type"] == "SUPPLIER"
    assert body["is_standalone_ledger"] is False


@pytest.mark.asyncio
async def test_journal_posts_to_standalone_ap_without_party(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    expense_id = next(
        item["account_id"]
        for item in roles.json()["data"]
        if item["role"] == "PURCHASES"
    )
    parent_id = await _ap_parent_id(client, headers)
    suffix = uuid4().hex[:6]
    ledger = await client.post(
        "/api/v1/accounts",
        headers=headers,
        json={
            "code": f"ST{suffix}",
            "name": f"Standalone AP {suffix}",
            "account_type": "LIABILITY",
            "account_subtype": "ACCOUNTS_PAYABLE",
            "parent_id": parent_id,
            "is_group": False,
            "is_standalone_ledger": True,
        },
    )
    assert ledger.status_code == 201, ledger.text
    ap_id = ledger.json()["data"]["id"]
    journal = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "entry_date": "2026-01-20",
            "lines": [
                {"account_id": expense_id, "debit": "25.00", "credit": "0"},
                {"account_id": ap_id, "debit": "0", "credit": "25.00"},
            ],
        },
    )
    assert journal.status_code == 201, journal.text
    row = journal.json()["data"]
    posted = await client.post(
        f"/api/v1/journals/{row['id']}/post",
        headers={**headers, "Idempotency-Key": uuid4().hex, "If-Match": str(row["version"])},
    )
    assert posted.status_code == 200, posted.text


@pytest.mark.asyncio
async def test_charge_type_rejects_unlinked_ap_account(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    parent_id = await _ap_parent_id(client, headers)
    suffix = uuid4().hex[:6]
    unlinked = await client.post(
        "/api/v1/accounts",
        headers=headers,
        json={
            "code": f"UN{suffix}",
            "name": f"Unlinked AP {suffix}",
            "account_type": "LIABILITY",
            "account_subtype": "ACCOUNTS_PAYABLE",
            "parent_id": parent_id,
            "is_group": False,
        },
    )
    assert unlinked.status_code == 201, unlinked.text
    account_id = unlinked.json()["data"]["id"]
    created = await client.post(
        "/api/v1/charge-types",
        headers=headers,
        json={
            "code": f"CT{suffix[:4]}",
            "name": f"Charge {suffix}",
            "default_account_id": account_id,
            "is_inventoriable": False,
            "applies_to": "BOTH",
        },
    )
    assert created.status_code == 422, created.text

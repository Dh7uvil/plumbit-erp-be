"""Budgets are plans. They never post to the ledger."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _leaf_account(client: AsyncClient, headers: dict[str, str]) -> str:
    listed = await client.get("/api/v1/accounts?page_size=100", headers=headers)
    assert listed.status_code == 200, listed.text
    for row in listed.json()["data"]:
        if row["is_group"] is False and row["account_type"] == "EXPENSE":
            return row["id"]
    raise AssertionError("expected a postable expense account")


@pytest.mark.asyncio
async def test_budget_activate_and_vs_actual_does_not_post(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    account_id = await _leaf_account(client, headers)
    period = date.today().replace(day=1).isoformat()
    created = await client.post(
        "/api/v1/budgets",
        headers=headers,
        json={
            "name": "FY plan",
            "fiscal_year": date.today().year,
            "lines": [{"account_id": account_id, "period_start": period, "amount": "250.0000"}],
        },
    )
    assert created.status_code == 201, created.text
    budget = created.json()["data"]
    assert budget["status"] == "DRAFT"
    assert "activate" in budget["available_actions"]
    empty = await client.post(
        "/api/v1/budgets",
        headers=headers,
        json={"name": "Empty", "fiscal_year": date.today().year, "lines": []},
    )
    assert empty.status_code == 201, empty.text
    blocked = await client.post(
        f"/api/v1/budgets/{empty.json()['data']['id']}/activate",
        headers={**headers, "If-Match": "1"},
    )
    assert blocked.status_code == 422, blocked.text
    activated = await client.post(
        f"/api/v1/budgets/{budget['id']}/activate",
        headers={**headers, "If-Match": str(budget["version"])},
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["data"]["status"] == "ACTIVE"
    compared = await client.get(
        f"/api/v1/budgets/{budget['id']}/vs-actual",
        headers=headers,
        params={"from": period, "to": date.today().isoformat()},
    )
    assert compared.status_code == 200, compared.text
    body = compared.json()["data"]
    assert Decimal(body["lines"][0]["budget_amount"]) == Decimal("250.0000")
    journals = await client.get("/api/v1/journals?page_size=5", headers=headers)
    assert journals.status_code == 200, journals.text
    assert journals.json()["meta"]["total"] == 0


@pytest.mark.asyncio
async def test_budget_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    created = await client.post(
        "/api/v1/budgets",
        headers=headers_a,
        json={"name": "Private", "fiscal_year": 2026},
    )
    assert created.status_code == 201, created.text
    budget_id = created.json()["data"]["id"]
    cross = await client.get(f"/api/v1/budgets/{budget_id}", headers=headers_b)
    assert cross.status_code == 404, cross.text

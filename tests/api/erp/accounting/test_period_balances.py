"""Account period balances by fiscal period."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _accounts(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    assert roles.status_code == 200, roles.text
    return {item["role"]: item["account_id"] for item in roles.json()["data"]}


@pytest.mark.asyncio
async def test_period_balances_track_posted_movement(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    cash_id = accounts["CASH_ON_HAND"]
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "lines": [
                {"account_id": cash_id, "debit": "25.0000", "credit": "0"},
                {"account_id": accounts["SALES_REVENUE"], "debit": "0", "credit": "25.0000"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    posted = await client.post(
        f"/api/v1/journals/{row['id']}/post",
        headers={**headers, "If-Match": str(row["version"]), "Idempotency-Key": "pb1"},
    )
    assert posted.status_code == 200, posted.text
    entry_date = posted.json()["data"]["entry_date"]
    response = await client.get(
        f"/api/v1/accounts/{cash_id}/period-balances",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["account_id"] == cash_id
    assert len(body["periods"]) >= 1
    period_with_activity = next(
        (period for period in body["periods"] if Decimal(period["debit"]) > Decimal("0")),
        None,
    )
    assert period_with_activity is not None
    assert period_with_activity["from_date"] <= entry_date <= period_with_activity["to_date"]
    assert Decimal(period_with_activity["debit"]) == Decimal("25.0000")
    assert Decimal(body["closing"]) == Decimal(period_with_activity["closing"])


@pytest.mark.asyncio
async def test_period_balances_respect_april_fiscal_year_start(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    updated = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"fiscal_year_start_month": 4, "fiscal_year_start_day": 1},
    )
    assert updated.status_code == 200, updated.text
    accounts = await _accounts(client, headers)
    cash_id = accounts["CASH_ON_HAND"]

    async def post_cash(amount: str, entry_date: str) -> None:
        created = await client.post(
            "/api/v1/journals",
            headers=headers,
            json={
                "entry_date": entry_date,
                "lines": [
                    {"account_id": cash_id, "debit": amount, "credit": "0"},
                    {
                        "account_id": accounts["SALES_REVENUE"],
                        "debit": "0",
                        "credit": amount,
                    },
                ],
            },
        )
        assert created.status_code == 201, created.text
        row = created.json()["data"]
        posted = await client.post(
            f"/api/v1/journals/{row['id']}/post",
            headers={
                **headers,
                "If-Match": str(row["version"]),
                "Idempotency-Key": f"pb-apr-{entry_date}-{amount}",
            },
        )
        assert posted.status_code == 200, posted.text

    await post_cash("10.0000", "2026-04-01")
    await post_cash("20.0000", "2026-05-15")

    response = await client.get(
        f"/api/v1/accounts/{cash_id}/period-balances",
        headers=headers,
        params={"fiscal_year": 2026},
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["fiscal_year"] == 2026
    by_period = {period["period"]: period for period in body["periods"]}
    assert by_period[1]["from_date"] == "2026-04-01"
    assert by_period[12]["to_date"] == "2027-03-31"
    assert Decimal(by_period[1]["debit"]) == Decimal("10.0000")
    assert Decimal(by_period[2]["debit"]) == Decimal("20.0000")
    assert Decimal(body["closing"]) == Decimal("30.0000")

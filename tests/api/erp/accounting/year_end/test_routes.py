"""Year-end closing preview, commit, reopen, and balance sheet integrity."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


def _idempotent(headers: dict[str, str], version: object) -> dict[str, str]:
    return {**headers, "If-Match": str(version), "Idempotency-Key": uuid4().hex}


async def _accounts(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    assert roles.status_code == 200, roles.text
    return {item["role"]: item["account_id"] for item in roles.json()["data"]}


async def _enable_books(client: AsyncClient, headers: dict[str, str]) -> None:
    updated = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"books_start_date": "2026-01-01"},
    )
    assert updated.status_code == 200, updated.text


async def _post_cash_sale(
    client: AsyncClient,
    headers: dict[str, str],
    accounts: dict[str, str],
    *,
    amount: str,
    entry_date: str,
) -> None:
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "entry_date": entry_date,
            "narration": "Cash sale",
            "lines": [
                {"account_id": accounts["BANK"], "debit": amount, "credit": "0"},
                {"account_id": accounts["SALES_REVENUE"], "debit": "0", "credit": amount},
            ],
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    posted = await client.post(
        f"/api/v1/journals/{row['id']}/post",
        headers=_idempotent(headers, row["version"]),
    )
    assert posted.status_code == 200, posted.text


@pytest.mark.asyncio
async def test_year_end_preview_commit_reopen_and_balance_sheet_no_double_count(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    await _post_cash_sale(
        client,
        headers,
        accounts,
        amount="80.0000",
        entry_date="2026-06-15",
    )

    fiscal_year = 2026
    preview = await client.post(
        "/api/v1/year-end/preview",
        headers=headers,
        json={"fiscal_year": fiscal_year},
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()["data"]
    assert preview_body["from_date"] == "2026-01-01"
    assert preview_body["to_date"] == "2026-12-31"
    assert Decimal(preview_body["net_profit"]) == Decimal("80.0000")
    assert Decimal(preview_body["total_debit"]) == Decimal(preview_body["total_credit"])

    before_close = await client.get(
        "/api/v1/reports/balance-sheet",
        headers=headers,
        params={"as_of": "2026-12-31"},
    )
    assert before_close.status_code == 200, before_close.text
    before = before_close.json()["data"]
    assert Decimal(before["current_earnings"]) == Decimal("80.0000")
    equity_before = Decimal(before["total_equity"])

    committed = await client.post(
        "/api/v1/year-end/commit",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"fiscal_year": fiscal_year},
    )
    assert committed.status_code == 200, committed.text
    state = committed.json()["data"]
    assert state["is_closed"] is True
    assert state["journal_entry_id"] is not None

    after_close = await client.get(
        "/api/v1/reports/balance-sheet",
        headers=headers,
        params={"as_of": "2026-12-31"},
    )
    assert after_close.status_code == 200, after_close.text
    after = after_close.json()["data"]
    assert Decimal(after["current_earnings"]) == Decimal("0.0000")
    assert after["is_balanced"] is True
    retained = next(
        line
        for line in after["lines"]
        if line["account_id"] == accounts["RETAINED_EARNINGS"]
    )
    assert Decimal(retained["amount"]) == Decimal("80.0000")
    assert Decimal(after["total_equity"]) == equity_before
    current_earnings_lines = [
        line for line in after["lines"] if line["account_name"] == "Current earnings"
    ]
    assert current_earnings_lines == []

    reopened = await client.post(
        "/api/v1/year-end/reopen",
        headers=headers,
        json={"fiscal_year": fiscal_year},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["data"]["is_closed"] is False

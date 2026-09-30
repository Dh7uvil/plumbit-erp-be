"""Account statement permutations: party, GL account, PDC."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.accounting.test_banking import _bank_account, _enable_books, _posted_invoice
from tests.conftest import login_headers, provision_admin


async def _accounts(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    assert roles.status_code == 200, roles.text
    return {item["role"]: item["account_id"] for item in roles.json()["data"]}


@pytest.mark.asyncio
async def test_account_statement_by_gl_account(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    bank_id = accounts["BANK"]
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "lines": [
                {"account_id": bank_id, "debit": "50.0000", "credit": "0"},
                {"account_id": accounts["SALES_REVENUE"], "debit": "0", "credit": "50.0000"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    posted = await client.post(
        f"/api/v1/journals/{row['id']}/post",
        headers={**headers, "If-Match": str(row["version"]), "Idempotency-Key": uuid4().hex},
    )
    assert posted.status_code == 200, posted.text
    entry_date = posted.json()["data"]["entry_date"]
    statement = await client.get(
        "/api/v1/reports/account-statement",
        headers=headers,
        params={"account_id": bank_id, "from": entry_date, "to": entry_date},
    )
    assert statement.status_code == 200, statement.text
    data = statement.json()["data"]
    assert data["account_id"] == bank_id
    assert Decimal(data["closing_balance"]) == Decimal("50.0000")
    assert data["lines"][0]["voucher_code"] == "JV"


@pytest.mark.asyncio
async def test_account_statement_include_pdc_pending_line(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    bank = await _bank_account(client, headers)
    invoice = await _posted_invoice(client, headers)
    total = Decimal(str(invoice["grand_total"]))
    created = await client.post(
        "/api/v1/cheques",
        headers=headers,
        json={
            "cheque_number": "PDC-STMT-1",
            "direction": "INBOUND",
            "cheque_date": "2026-12-15",
            "due_date": "2026-12-15",
            "amount": str(total),
            "currency_id": invoice["currency_id"],
            "party_type": "CUSTOMER",
            "party_id": invoice["customer_id"],
            "bank_account_id": bank["id"],
        },
    )
    assert created.status_code == 201, created.text
    cheque = created.json()["data"]
    issued = await client.post(
        f"/api/v1/cheques/{cheque['id']}/issue",
        headers={**headers, "If-Match": str(cheque["version"]), "Idempotency-Key": uuid4().hex},
    )
    assert issued.status_code == 200, issued.text
    statement = await client.get(
        "/api/v1/reports/account-statement",
        headers=headers,
        params={
            "party_type": "CUSTOMER",
            "party_id": invoice["customer_id"],
            "from": "2026-12-01",
            "to": "2026-12-31",
            "include_pdc": "true",
        },
    )
    assert statement.status_code == 200, statement.text
    data = statement.json()["data"]
    pdc_lines = [line for line in data["lines"] if line.get("voucher_code") == "PD"]
    assert len(pdc_lines) == 1
    assert pdc_lines[0]["cheque_number"] == "PDC-STMT-1"


@pytest.mark.asyncio
async def test_account_statement_exclude_opening_balance(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    bank_id = accounts["BANK"]

    async def post_bank(amount: str, entry_date: str) -> None:
        created = await client.post(
            "/api/v1/journals",
            headers=headers,
            json={
                "entry_date": entry_date,
                "lines": [
                    {"account_id": bank_id, "debit": amount, "credit": "0"},
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
            headers={**headers, "If-Match": str(row["version"]), "Idempotency-Key": uuid4().hex},
        )
        assert posted.status_code == 200, posted.text

    await post_bank("100.0000", "2026-06-01")
    await post_bank("25.0000", "2026-06-15")

    statement = await client.get(
        "/api/v1/reports/account-statement",
        headers=headers,
        params={
            "account_id": bank_id,
            "from": "2026-06-15",
            "to": "2026-06-15",
            "include_opening": "false",
        },
    )
    assert statement.status_code == 200, statement.text
    data = statement.json()["data"]
    assert data["opening"] is None
    assert Decimal(data["opening_balance"]) == Decimal("100.0000")
    assert Decimal(data["closing_balance"]) == Decimal("25.0000")
    assert len(data["lines"]) == 1
    assert Decimal(data["lines"][0]["debit"]) == Decimal("25.0000")
    assert Decimal(data["lines"][0]["running_balance"]) == Decimal("25.0000")

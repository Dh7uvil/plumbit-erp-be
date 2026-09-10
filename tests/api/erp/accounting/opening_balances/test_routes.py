"""API tests for opening balances, trial balance, and numbering regression."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _accounts(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    assert roles.status_code == 200, roles.text
    return {item["role"]: item["account_id"] for item in roles.json()["data"]}


@pytest.mark.asyncio
async def test_opening_balances_commit_balances_trial_balance(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    books_start = datetime.now(UTC).date() + timedelta(days=1)
    payload = {
        "books_start_date": books_start.isoformat(),
        "gl_lines": [
            {"account_id": accounts["BANK"], "debit": "1000.0000", "credit": "0"},
        ],
        "ar_items": [],
        "ap_items": [],
        "stock_lines": [],
    }
    preview = await client.post("/api/v1/opening-balances/preview", headers=headers, json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["difference"] == "1000.0000"
    committed = await client.post(
        "/api/v1/opening-balances/commit",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json=payload,
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["data"]["committed"] is True
    entry_date = books_start - timedelta(days=1)
    tb = await client.get(
        "/api/v1/reports/trial-balance",
        headers=headers,
        params={"from": entry_date.isoformat(), "to": books_start.isoformat()},
    )
    assert tb.status_code == 200, tb.text
    body = tb.json()["data"]
    assert body["is_balanced"] is True
    assert body["total_closing_debit"] == body["total_closing_credit"]


@pytest.mark.asyncio
async def test_document_numbering_unchanged_at_january_default(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    org = await client.get("/api/v1/tenants/current", headers=headers)
    assert org.status_code == 200, org.text
    assert org.json()["data"]["fiscal_year_start_month"] == 1
    assert org.json()["data"]["fiscal_year_start_day"] == 1
    units = await client.get("/api/v1/units?page_size=100", headers=headers)
    pcs = next(item for item in units.json()["data"] if item["code"] == "PCS")
    customer = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "name": "Numbering customer",
            "code": f"C-{uuid4().hex[:8]}",
            "tax_treatment": "UNREGISTERED",
        },
    )
    assert customer.status_code == 201, customer.text
    product = await client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "sku": f"SKU-{uuid4().hex[:8]}",
            "name": "Widget",
            "unit_id": pcs["id"],
            "selling_rate": "10.0000",
        },
    )
    assert product.status_code == 201, product.text
    quote = await client.post(
        "/api/v1/quotations",
        headers=headers,
        json={
            "customer_id": customer.json()["data"]["id"],
            "lines": [{"product_id": product.json()["data"]["id"], "quantity": "1"}],
        },
    )
    assert quote.status_code == 201, quote.text
    timezone = org.json()["data"]["timezone"]
    year = datetime.now(ZoneInfo(timezone)).year
    assert quote.json()["data"]["quote_number"].startswith(f"QUO-{year}-")

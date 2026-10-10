"""Entry book master API."""

import pytest
from httpx import AsyncClient

from tests.api.erp.customer_payments.test_routes import _enable_books
from tests.conftest import login_headers, provision_admin

_EXPECTED_TYPES = frozenset(
    {
        "CASH_RECEIPT",
        "CASH_PAYMENT",
        "BANK_RECEIPT",
        "BANK_PAYMENT",
        "JOURNAL",
        "GENERAL_PURCHASE",
        "PAYMENT_VOUCHER",
    }
)


@pytest.mark.asyncio
async def test_entry_books_list_seeds_defaults(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    listed = await client.get(
        "/api/v1/entry-books",
        headers=headers,
        params={"page_size": 50, "is_active": True},
    )
    assert listed.status_code == 200, listed.text
    rows = listed.json()["data"]
    types = {row["voucher_type"] for row in rows}
    assert _EXPECTED_TYPES.issubset(types)
    gp = next(row for row in rows if row["voucher_type"] == "GENERAL_PURCHASE")
    assert gp["series_prefix"] == "GP"


@pytest.mark.asyncio
async def test_entry_book_series_update(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    listed = await client.get("/api/v1/entry-books", headers=headers, params={"page_size": 50})
    assert listed.status_code == 200, listed.text
    pv = next(row for row in listed.json()["data"] if row["voucher_type"] == "PAYMENT_VOUCHER")
    patched = await client.patch(
        f"/api/v1/entry-books/{pv['id']}",
        headers=headers,
        json={"series_prefix": "PVX"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["series_prefix"] == "PVX"

"""Currency sort allowlists, invalid sort mapping, and FX nearest-date resolve."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_currencies_list_sort_by_is_base_succeeds(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    listed = await client.get(
        "/api/v1/currencies?sort_by=is_base&sort_order=desc&page_size=20",
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    rows = listed.json()["data"]
    assert rows
    assert any(item["code"] == "AED" and item["is_base"] is True for item in rows)


@pytest.mark.asyncio
async def test_currencies_default_list_returns_200(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    listed = await client.get("/api/v1/currencies?sort_by=code&sort_order=asc", headers=headers)
    assert listed.status_code == 200, listed.text
    codes = [item["code"] for item in listed.json()["data"]]
    assert "AED" in codes


@pytest.mark.asyncio
async def test_invalid_currency_sort_returns_422(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    listed = await client.get("/api/v1/currencies?sort_by=not_a_field", headers=headers)
    assert listed.status_code == 422, listed.text
    assert listed.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_cannot_delete_base_currency(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    listed = await client.get("/api/v1/currencies?is_base=true", headers=headers)
    assert listed.status_code == 200, listed.text
    currency_id = listed.json()["data"][0]["id"]
    deleted = await client.delete(f"/api/v1/currencies/{currency_id}", headers=headers)
    assert deleted.status_code == 422, deleted.text
    assert deleted.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_exchange_rate_resolve_falls_back_to_latest_prior_date(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    usd = await client.get("/api/v1/currencies?search=USD", headers=headers)
    usd_id = next(item["id"] for item in usd.json()["data"] if item["code"] == "USD")
    effective = date.today() - timedelta(days=10)
    saved = await client.put(
        "/api/v1/exchange-rates",
        headers=headers,
        json={
            "currency_id": usd_id,
            "rate_to_base": "3.6725",
            "effective_date": effective.isoformat(),
        },
    )
    assert saved.status_code == 200, saved.text
    later = effective + timedelta(days=5)
    resolved = await client.get(
        f"/api/v1/exchange-rates/resolve?from_currency_id={usd_id}&on_date={later.isoformat()}",
        headers=headers,
    )
    assert resolved.status_code == 200, resolved.text
    data = resolved.json()["data"]
    assert data["effective_date"] == effective.isoformat()
    assert Decimal(data["rate"]) == Decimal("3.6725")

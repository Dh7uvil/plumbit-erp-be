"""Tenant isolation for currencies and exchange rates."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_currency_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    listed_a = await client.get("/api/v1/currencies?is_base=true", headers=headers_a)
    assert listed_a.status_code == 200, listed_a.text
    currency_id = listed_a.json()["data"][0]["id"]
    fetched = await client.get(f"/api/v1/currencies/{currency_id}", headers=headers_b)
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    listed_b = await client.get("/api/v1/currencies?is_base=true", headers=headers_b)
    assert listed_b.status_code == 200
    assert all(item["id"] != currency_id for item in listed_b.json()["data"])


@pytest.mark.asyncio
async def test_exchange_rate_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    usd_a = await client.get("/api/v1/currencies?search=USD", headers=headers_a)
    assert usd_a.status_code == 200, usd_a.text
    usd_id = next(item["id"] for item in usd_a.json()["data"] if item["code"] == "USD")
    saved = await client.put(
        "/api/v1/exchange-rates",
        headers=headers_a,
        json={"currency_id": usd_id, "rate_to_base": "3.6725"},
    )
    assert saved.status_code == 200, saved.text
    rate_id = saved.json()["data"]["id"]
    listed_b = await client.get("/api/v1/exchange-rates", headers=headers_b)
    assert listed_b.status_code == 200, listed_b.text
    assert all(item["id"] != rate_id for item in listed_b.json()["data"])
    usd_b = await client.get("/api/v1/currencies?search=USD", headers=headers_b)
    usd_b_id = next(item["id"] for item in usd_b.json()["data"] if item["code"] == "USD")
    missing = await client.get(
        f"/api/v1/exchange-rates/resolve?from_currency_id={usd_b_id}",
        headers=headers_b,
    )
    assert missing.status_code == 422, missing.text
    assert missing.json()["error"]["code"] == "EXCHANGE_RATE_MISSING"


@pytest.mark.asyncio
async def test_exchange_rate_list_is_paginated_and_patch_updates(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    usd = await client.get("/api/v1/currencies?search=USD", headers=headers)
    usd_id = next(item["id"] for item in usd.json()["data"] if item["code"] == "USD")
    saved = await client.put(
        "/api/v1/exchange-rates",
        headers=headers,
        json={"currency_id": usd_id, "rate_to_base": "3.6725"},
    )
    assert saved.status_code == 200, saved.text
    rate_id = saved.json()["data"]["id"]
    listed = await client.get("/api/v1/exchange-rates", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["meta"]["total"] >= 1
    patched = await client.patch(
        f"/api/v1/exchange-rates/{rate_id}",
        headers=headers,
        json={"rate_to_base": "3.6800"},
    )
    assert patched.status_code == 200, patched.text
    assert Decimal(patched.json()["data"]["rate"]) == Decimal("3.680000")

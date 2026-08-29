"""API tests for tenant creation seeds, required masters, and common backfill."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.cli.seed_tenants import seed_existing_tenants
from app.db.seeds.common import seed_common_data
from app.db.seeds.required import seed_required_masters
from app.db.session import async_session_factory, transaction
from app.erp.exchange_rates.catalog import ISO_4217_CURRENCIES
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_provisioned_tenant_seeds_iso_currencies_with_aed_base(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)

    listed = await client.get("/api/v1/currencies?page_size=100", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["meta"]["total"] == len(ISO_4217_CURRENCIES)

    base = await client.get("/api/v1/currencies?is_base=true", headers=headers)
    assert base.status_code == 200, base.text
    rows = base.json()["data"]
    assert len(rows) == 1
    assert rows[0]["code"] == "AED"
    assert rows[0]["is_base"] is True

    duplicate = await client.post(
        "/api/v1/currencies",
        headers=headers,
        json={"code": "USD", "name": "US Dollar", "symbol": "$"},
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["error"]["code"] == "DUPLICATE_RESOURCE"


@pytest.mark.asyncio
async def test_provisioned_tenant_seeds_required_masters(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)

    warehouses = await client.get("/api/v1/warehouses?search=MAIN", headers=headers)
    assert warehouses.status_code == 200, warehouses.text
    assert warehouses.json()["meta"]["total"] == 1
    assert warehouses.json()["data"][0]["is_default"] is True

    taxes = await client.get("/api/v1/taxes?page_size=100", headers=headers)
    assert taxes.status_code == 200, taxes.text
    assert taxes.json()["meta"]["total"] == 4
    assert {item["name"] for item in taxes.json()["data"]} == {
        "Standard VAT 5%",
        "Zero Rated",
        "Exempt",
        "Out of Scope",
    }

    units = await client.get("/api/v1/units?page_size=100", headers=headers)
    assert units.status_code == 200, units.text
    assert {item["code"] for item in units.json()["data"]} >= {"PCS", "BOX", "M", "KG"}

    terms = await client.get("/api/v1/payment-terms?search=Net%2030", headers=headers)
    assert terms.status_code == 200, terms.text
    assert terms.json()["meta"]["total"] == 1

    templates = await client.get("/api/v1/terms-templates?search=Standard", headers=headers)
    assert templates.status_code == 200, templates.text
    assert templates.json()["meta"]["total"] == 1
    assert templates.json()["data"][0]["is_default"] is True

    sequences = await client.get("/api/v1/document-sequences?search=QUO", headers=headers)
    assert sequences.status_code == 200, sequences.text
    assert sequences.json()["meta"]["total"] == 1


@pytest.mark.asyncio
async def test_seed_existing_tenants_is_idempotent(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    results = await seed_existing_tenants(tenant_id=UUID(tenant_id))
    assert len(results) == 1
    assert results[0].currencies_inserted == 0
    headers = await login_headers(client, tenant_id, email, password)
    listed = await client.get("/api/v1/currencies?page_size=100", headers=headers)
    assert listed.json()["meta"]["total"] == len(ISO_4217_CURRENCIES)


@pytest.mark.asyncio
async def test_seed_common_data_backfills_missing_currency(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    usd = await client.get("/api/v1/currencies?search=USD", headers=headers)
    assert usd.status_code == 200, usd.text
    usd_id = next(item["id"] for item in usd.json()["data"] if item["code"] == "USD")
    deleted = await client.delete(f"/api/v1/currencies/{usd_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text

    async with async_session_factory() as session, transaction(session):
        inserted = await seed_common_data(session, UUID(tenant_id))
    assert inserted == 1

    restored = await client.get("/api/v1/currencies?search=USD", headers=headers)
    assert restored.status_code == 200, restored.text
    assert any(item["code"] == "USD" for item in restored.json()["data"])


@pytest.mark.asyncio
async def test_seed_required_masters_is_idempotent(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)

    async with async_session_factory() as session, transaction(session):
        await seed_required_masters(session, UUID(tenant_id))

    warehouses = await client.get("/api/v1/warehouses?search=MAIN", headers=headers)
    assert warehouses.status_code == 200, warehouses.text
    assert warehouses.json()["meta"]["total"] == 1
    taxes = await client.get("/api/v1/taxes?page_size=100", headers=headers)
    assert taxes.status_code == 200, taxes.text
    assert taxes.json()["meta"]["total"] == 4


@pytest.mark.asyncio
async def test_seed_existing_tenants_rejects_unknown_tenant() -> None:
    with pytest.raises(ValueError, match="No active tenant matched"):
        await seed_existing_tenants(tenant_id=uuid4())

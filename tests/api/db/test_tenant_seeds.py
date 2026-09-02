"""API tests for tenant creation seeds, required masters, and common backfill."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.cli.seed_tenants import seed_existing_tenants
from app.db.seeds.common import seed_common_data
from app.db.seeds.required import seed_required_masters
from app.db.session import async_session_factory, transaction
from app.erp.exchange_rates.catalog import ISO_4217_CURRENCIES
from tests.conftest import login_headers, provision_admin

_CANONICAL_SEQUENCE_PREFIXES = {
    "QUOTATION": "QUO",
    "SALES_ORDER": "SO",
    "DELIVERY_NOTE": "DN",
    "SALES_INVOICE": "INV",
    "CREDIT_NOTE": "CN",
    "PURCHASE_ORDER": "PO",
    "GOODS_RECEIPT": "GRN",
    "PURCHASE_INVOICE": "BILL",
    "DEBIT_NOTE": "SDN",
}


async def _list_sequences(client: AsyncClient, headers: dict[str, str]) -> list[dict[str, object]]:
    listed = await client.get("/api/v1/document-sequences?page_size=100", headers=headers)
    assert listed.status_code == 200, listed.text
    return listed.json()["data"]


def _assert_canonical_sequences(rows: list[dict[str, object]]) -> None:
    year = datetime.now(UTC).year
    assert len(rows) == len(_CANONICAL_SEQUENCE_PREFIXES)
    by_type = {item["document_type"]: item for item in rows}
    assert set(by_type) == set(_CANONICAL_SEQUENCE_PREFIXES)
    for document_type, prefix in _CANONICAL_SEQUENCE_PREFIXES.items():
        row = by_type[document_type]
        assert row["series"] == prefix
        assert row["prefix"] == prefix
        assert row["padding"] == 6
        assert row["fiscal_year"] == year


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

    sequences = await _list_sequences(client, headers)
    _assert_canonical_sequences(sequences)


@pytest.mark.asyncio
async def test_seed_existing_tenants_is_idempotent(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    results = await seed_existing_tenants(tenant_id=UUID(tenant_id))
    assert len(results) == 1
    assert results[0].currencies_inserted == 0
    headers = await login_headers(client, tenant_id, email, password)
    listed = await client.get("/api/v1/currencies?page_size=100", headers=headers)
    assert listed.json()["meta"]["total"] == len(ISO_4217_CURRENCIES)
    _assert_canonical_sequences(await _list_sequences(client, headers))


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
async def test_seed_required_masters_does_not_steal_existing_defaults(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)

    main = (await client.get("/api/v1/warehouses?search=MAIN", headers=headers)).json()["data"][0]
    site = await client.post(
        "/api/v1/warehouses",
        headers=headers,
        json={"code": "SITE", "name": "Site Warehouse", "is_default": True},
    )
    assert site.status_code == 201, site.text
    deleted_main = await client.delete(f"/api/v1/warehouses/{main['id']}", headers=headers)
    assert deleted_main.status_code == 200, deleted_main.text

    results = await seed_existing_tenants(tenant_id=UUID(tenant_id))
    assert len(results) == 1

    warehouses = await client.get("/api/v1/warehouses?page_size=100", headers=headers)
    assert warehouses.status_code == 200, warehouses.text
    by_code = {item["code"]: item for item in warehouses.json()["data"]}
    assert by_code["SITE"]["is_default"] is True
    assert by_code["MAIN"]["is_default"] is False


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
    _assert_canonical_sequences(await _list_sequences(client, headers))


@pytest.mark.asyncio
async def test_seed_required_masters_restores_prefix_without_resetting_next_number(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    sequences = await _list_sequences(client, headers)
    quotation = next(item for item in sequences if item["document_type"] == "QUOTATION")

    drifted = await client.patch(
        f"/api/v1/document-sequences/{quotation['id']}",
        headers=headers,
        json={"prefix": "QQQ", "padding": 4, "next_number": 42},
    )
    assert drifted.status_code == 200, drifted.text
    assert drifted.json()["data"]["prefix"] == "QQQ"
    assert drifted.json()["data"]["padding"] == 4
    assert drifted.json()["data"]["next_number"] == 42

    async with async_session_factory() as session, transaction(session):
        await seed_required_masters(session, UUID(tenant_id))

    restored = await client.get(
        f"/api/v1/document-sequences/{quotation['id']}",
        headers=headers,
    )
    assert restored.status_code == 200, restored.text
    data = restored.json()["data"]
    assert data["prefix"] == "QUO"
    assert data["padding"] == 6
    assert data["next_number"] == 42
    _assert_canonical_sequences(await _list_sequences(client, headers))


@pytest.mark.asyncio
async def test_seed_existing_tenants_backfills_missing_document_sequence(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    sequences = await _list_sequences(client, headers)
    debit = next(item for item in sequences if item["document_type"] == "DEBIT_NOTE")
    deleted = await client.delete(
        f"/api/v1/document-sequences/{debit['id']}",
        headers=headers,
    )
    assert deleted.status_code == 200, deleted.text

    await seed_existing_tenants(tenant_id=UUID(tenant_id))
    _assert_canonical_sequences(await _list_sequences(client, headers))


@pytest.mark.asyncio
async def test_seed_existing_tenants_rejects_unknown_tenant() -> None:
    with pytest.raises(ValueError, match="No active tenant matched"):
        await seed_existing_tenants(tenant_id=uuid4())

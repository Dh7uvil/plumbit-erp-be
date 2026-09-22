"""Phase 1 multi-currency journal, reciprocal FX, and missing-rate report tests."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.common.utils.currency import quantize_money, quantize_rate
from app.erp.accounting.reports.analytical import _converted_amounts
from tests.api.erp.accounting.ledger.test_routes import _accounts, _if_match
from tests.api.erp.purchase_invoices.test_routes import _enable_books
from tests.api.erp.purchase_orders.test_routes import (
    _create_product as _create_purchase_product,
)
from tests.api.erp.purchase_orders.test_routes import (
    _create_supplier,
)
from tests.api.erp.purchase_orders.test_routes import (
    _if_match as _po_if_match,
)
from tests.api.erp.quotation.test_routes import _currency_id, _seeded_ids
from tests.api.inventory_management.goods_receipts.test_routes import (
    _create_from_po,
    _post_grn,
)
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_mixed_currency_draft_journal_balances_in_base(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    usd_id = await _currency_id(client, headers, "USD")
    aed = await client.get("/api/v1/currencies?is_base=true", headers=headers)
    aed_id = aed.json()["data"][0]["id"]
    saved = await client.put(
        "/api/v1/exchange-rates",
        headers=headers,
        json={"currency_id": usd_id, "rate_to_base": "3.672500"},
    )
    assert saved.status_code == 200, saved.text
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "currency_id": aed_id,
            "exchange_rate": "1",
            "narration": "Mixed currency transfer",
            "lines": [
                {
                    "account_id": accounts["BANK"],
                    "debit": "100.0000",
                    "credit": "0",
                    "currency_id": usd_id,
                    "exchange_rate": "3.672500",
                },
                {
                    "account_id": accounts["CASH_ON_HAND"],
                    "debit": "0",
                    "credit": "367.2500",
                    "currency_id": aed_id,
                    "exchange_rate": "1",
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    assert Decimal(row["total_debit_base"]) == Decimal("367.2500")
    assert Decimal(row["total_credit_base"]) == Decimal("367.2500")
    assert row["warnings"] == []
    posted = await client.post(
        f"/api/v1/journals/{row['id']}/post",
        headers=_if_match(headers, row["version"], key=uuid4().hex),
    )
    assert posted.status_code == 200, posted.text
    body = posted.json()["data"]
    assert body["status"] == "POSTED"
    assert Decimal(body["total_debit_base"]) == Decimal("367.2500")
    assert Decimal(body["total_credit_base"]) == Decimal("367.2500")


@pytest.mark.asyncio
async def test_draft_journal_quantizes_base_amounts(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "lines": [
                {
                    "account_id": accounts["BANK"],
                    "debit": "100.0001",
                    "credit": "0",
                    "exchange_rate": "3.333333",
                },
                {
                    "account_id": accounts["CASH_ON_HAND"],
                    "debit": "0",
                    "credit": "333.3337",
                    "exchange_rate": "1",
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    debit_base = Decimal(row["lines"][0]["debit_base"])
    assert debit_base == quantize_money(Decimal("100.0001") * Decimal("3.333333"))
    assert Decimal(row["total_debit_base"]) == debit_base


@pytest.mark.asyncio
async def test_exchange_rate_resolve_uses_reciprocal_pair(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    usd_id = await _currency_id(client, headers, "USD")
    aed = await client.get("/api/v1/currencies?is_base=true", headers=headers)
    aed_id = aed.json()["data"][0]["id"]
    saved = await client.put(
        "/api/v1/exchange-rates",
        headers=headers,
        json={"currency_id": usd_id, "rate_to_base": "3.672500"},
    )
    assert saved.status_code == 200, saved.text
    resolved = await client.get(
        f"/api/v1/exchange-rates/resolve?from_currency_id={aed_id}&to_currency_id={usd_id}",
        headers=headers,
    )
    assert resolved.status_code == 200, resolved.text
    data = resolved.json()["data"]
    assert data["is_derived_reciprocal"] is True
    assert Decimal(data["rate"]) == quantize_rate(Decimal("1") / Decimal("3.672500"))


@pytest.mark.asyncio
async def test_exchange_rate_upsert_warns_when_rate_looks_inverted(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    usd_id = await _currency_id(client, headers, "USD")
    prior = date.today() - timedelta(days=1)
    first = await client.put(
        "/api/v1/exchange-rates",
        headers=headers,
        json={
            "currency_id": usd_id,
            "rate_to_base": "3.672500",
            "effective_date": prior.isoformat(),
        },
    )
    assert first.status_code == 200, first.text
    inverted = await client.put(
        "/api/v1/exchange-rates",
        headers=headers,
        json={"currency_id": usd_id, "rate_to_base": "0.272300"},
    )
    assert inverted.status_code == 200, inverted.text
    warnings = inverted.json()["data"]["warnings"]
    assert any("inverted" in warning.lower() for warning in warnings)


def test_analytical_excludes_document_when_rate_is_missing() -> None:
    warnings: list[str] = []
    document = SimpleNamespace(
        document_number="INV-MISSING",
        exchange_rate=None,
        base_amount=None,
        grand_total=Decimal("100.0000"),
        tax_amount=Decimal("5.0000"),
    )
    assert _converted_amounts(document, sign=Decimal("1"), warnings=warnings) is None
    assert warnings == ["Excluded INV-MISSING: exchange rate missing"]


@pytest.mark.asyncio
async def test_grn_stores_base_amount_at_cross_rate(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    usd_id = await _currency_id(client, headers, "USD")
    fx_rate = Decimal("3.672500")
    saved = await client.put(
        "/api/v1/exchange-rates",
        headers=headers,
        json={"currency_id": usd_id, "rate_to_base": str(fx_rate)},
    )
    assert saved.status_code == 200, saved.text
    ids = await _seeded_ids(client, headers)
    supplier_id = await _create_supplier(client, headers)
    product_id = await _create_purchase_product(
        client, headers, ids, track_inventory=True, purchase_rate="40.0000"
    )
    po = await client.post(
        "/api/v1/purchase-orders",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "currency_id": usd_id,
            "lines": [{"product_id": product_id, "quantity": "2", "rate": "40.0000"}],
        },
    )
    assert po.status_code == 201, po.text
    issued = await client.post(
        f"/api/v1/purchase-orders/{po.json()['data']['id']}/issue",
        headers=_po_if_match(headers, po.json()["data"]["version"]),
    )
    assert issued.status_code == 200, issued.text
    receipt = await _create_from_po(client, headers, issued.json()["data"]["id"])
    assert receipt["status_code"] == 201, receipt["text"]
    grn = receipt["body"]["data"]
    assert Decimal(grn["exchange_rate"]) == fx_rate
    assert Decimal(grn["foreign_amount"]) == Decimal("80.0000")
    assert Decimal(grn["base_amount"]) == quantize_money(Decimal("80.0000") * fx_rate)
    posted = await _post_grn(client, headers, grn["id"], grn["version"])
    assert posted.status_code == 200, posted.text
    stock = await client.get(f"/api/v1/stock?product_id={product_id}", headers=headers)
    row = stock.json()["data"][0]
    layers = await client.get(f"/api/v1/stock/{row['id']}/layers", headers=headers)
    assert Decimal(layers.json()["data"][0]["unit_cost"]) == quantize_money(
        Decimal("40.0000") * fx_rate
    )


def test_analytical_uses_stored_zero_base_amount() -> None:
    warnings: list[str] = []
    document = SimpleNamespace(
        document_number="INV-ZERO",
        exchange_rate=Decimal("3.6725"),
        base_amount=Decimal("0"),
        grand_total=Decimal("100.0000"),
        tax_amount=Decimal("5.0000"),
    )
    converted = _converted_amounts(document, sign=Decimal("1"), warnings=warnings)
    assert converted is not None
    net, tax, rate = converted
    assert net == Decimal("0.0000")
    assert tax == Decimal("18.3625")
    assert rate == Decimal("3.6725")
    assert warnings == []

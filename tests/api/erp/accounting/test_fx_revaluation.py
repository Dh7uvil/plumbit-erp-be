"""Unrealized FX moves the GL in base currency and leaves open items alone."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.erp.accounting.fx_revaluation.service import unrealized_gain
from tests.api.erp.customer_payments.test_routes import _enable_books
from tests.api.erp.quotation.test_routes import (
    _create_customer,
    _create_product,
    _currency_id,
    _seeded_ids,
)
from tests.conftest import login_headers, provision_admin


def test_unrealized_gain_sign() -> None:
    assert unrealized_gain(
        book_base=Decimal("100"), revalued_base=Decimal("110"), kind="AR"
    ) == Decimal("10.0000")
    assert unrealized_gain(
        book_base=Decimal("100"), revalued_base=Decimal("110"), kind="AP"
    ) == Decimal("-10.0000")


def _idempotent(headers: dict[str, str], version: object) -> dict[str, str]:
    return {**headers, "If-Match": str(version), "Idempotency-Key": uuid4().hex}


async def _usd_invoice(client: AsyncClient, headers: dict[str, str]) -> dict[str, object]:
    usd_id = await _currency_id(client, headers, "USD")
    saved = await client.put(
        "/api/v1/exchange-rates",
        headers=headers,
        json={"currency_id": usd_id, "rate_to_base": "3.672500"},
    )
    assert saved.status_code == 200, saved.text
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers, currency_id=usd_id)
    product_id = await _create_product(client, headers, ids, selling_rate="100.0000")
    created = await client.post(
        "/api/v1/sales-invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "currency_id": usd_id,
            "lines": [{"product_id": product_id, "quantity": "1"}],
        },
    )
    assert created.status_code == 201, created.text
    invoice = created.json()["data"]
    posted = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/post",
        headers=_idempotent(headers, invoice["version"]),
    )
    assert posted.status_code == 200, posted.text
    return posted.json()["data"]


@pytest.mark.asyncio
async def test_fx_revaluation_posts_gain_without_settling_the_invoice(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    invoice = await _usd_invoice(client, headers)
    usd_id = await _currency_id(client, headers, "USD")
    moved = await client.put(
        "/api/v1/exchange-rates",
        headers=headers,
        json={"currency_id": usd_id, "rate_to_base": "3.700000"},
    )
    assert moved.status_code == 200, moved.text
    as_of = date.today().isoformat()
    exposure = await client.get(
        "/api/v1/fx-revaluations/exposure", headers=headers, params={"as_of": as_of}
    )
    assert exposure.status_code == 200, exposure.text
    preview = exposure.json()["data"]
    assert Decimal(preview["total_gain_base"]) == Decimal("2.8875")
    ran = await client.post(
        "/api/v1/fx-revaluations/run",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"as_of": as_of},
    )
    assert ran.status_code == 200, ran.text
    run = ran.json()["data"]
    assert run["status"] == "POSTED"
    assert Decimal(run["total_gain_base"]) == Decimal("2.8875")
    blocked = await client.post(
        "/api/v1/fx-revaluations/run",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"as_of": as_of},
    )
    assert blocked.status_code == 422, blocked.text
    journal = await client.get(f"/api/v1/journals/{run['journal_entry_id']}", headers=headers)
    assert journal.status_code == 200, journal.text
    lines = journal.json()["data"]["lines"]
    assert any(
        line["party_id"] == invoice["customer_id"] and Decimal(line["debit"]) > 0 for line in lines
    )
    untouched = await client.get(f"/api/v1/sales-invoices/{invoice['id']}", headers=headers)
    assert untouched.status_code == 200, untouched.text
    still = untouched.json()["data"]
    assert Decimal(still["balance_due"]) == Decimal("105.0000")
    assert Decimal(still["exchange_rate"]) == Decimal("3.672500")
    reversal_date = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
    reversed_run = await client.post(
        f"/api/v1/fx-revaluations/{run['id']}/reverse",
        headers=_idempotent(headers, run["version"]),
        json={"reversal_date": reversal_date, "version": run["version"]},
    )
    assert reversed_run.status_code == 200, reversed_run.text
    assert reversed_run.json()["data"]["status"] == "REVERSED"


@pytest.mark.asyncio
async def test_fx_revaluation_without_exposure_is_rejected(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    ran = await client.post(
        "/api/v1/fx-revaluations/run",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"as_of": date.today().isoformat()},
    )
    assert ran.status_code == 422, ran.text


@pytest.mark.asyncio
async def test_fx_revaluation_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    await _enable_books(client, headers_a)
    await _usd_invoice(client, headers_a)
    usd_id = await _currency_id(client, headers_a, "USD")
    await client.put(
        "/api/v1/exchange-rates",
        headers=headers_a,
        json={"currency_id": usd_id, "rate_to_base": "3.700000"},
    )
    ran = await client.post(
        "/api/v1/fx-revaluations/run",
        headers={**headers_a, "Idempotency-Key": uuid4().hex},
        json={"as_of": date.today().isoformat()},
    )
    assert ran.status_code == 200, ran.text
    run_id = ran.json()["data"]["id"]
    cross = await client.get(f"/api/v1/fx-revaluations/{run_id}", headers=headers_b)
    assert cross.status_code == 404, cross.text

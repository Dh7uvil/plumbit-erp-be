"""API tests for the quotation → PFI → sales order conversion chain."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.quotation.test_routes import (
    _create_customer,
    _create_product,
    _create_quote,
    _if_match,
    _seeded_ids,
    _send_quote,
)
from tests.conftest import login_headers, provision_admin


def _idempotent(
    headers: dict[str, str], version: object, *, key: str | None = None
) -> dict[str, str]:
    return {**_if_match(headers, version), "Idempotency-Key": key or str(uuid4())}


async def _raise_pfi(
    client: AsyncClient, headers: dict[str, str], quote: dict[str, object]
) -> dict[str, object]:
    response = await client.post(
        f"/api/v1/quotations/{quote['id']}/convert-to-proforma-invoice",
        headers=_if_match(headers, quote["version"]),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _send_and_confirm_pfi(
    client: AsyncClient, headers: dict[str, str], pfi: dict[str, object]
) -> dict[str, object]:
    sent = await client.post(
        f"/api/v1/proforma-invoices/{pfi['id']}/send",
        headers=_if_match(headers, pfi["version"]),
    )
    assert sent.status_code == 200, sent.text
    confirmed = await client.post(
        f"/api/v1/proforma-invoices/{pfi['id']}/confirm",
        headers=_if_match(headers, sent.json()["data"]["version"]),
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()["data"]


@pytest.mark.asyncio
async def test_pfi_conversion_chain_and_idempotent_replay(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    quote = await _send_quote(client, headers, created["body"]["data"])
    pfi = await _raise_pfi(client, headers, quote)

    still_sent = await client.get(f"/api/v1/quotations/{quote['id']}", headers=headers)
    assert still_sent.json()["data"]["status"] == "SENT"
    assert still_sent.json()["data"]["converted_document_id"] is None

    confirmed = await _send_and_confirm_pfi(client, headers, pfi)
    accepted = await client.get(f"/api/v1/quotations/{quote['id']}", headers=headers)
    assert accepted.json()["data"]["status"] == "ACCEPTED"

    direct = await client.post(
        f"/api/v1/quotations/{quote['id']}/convert-to-sales-order",
        headers=_idempotent(headers, accepted.json()["data"]["version"]),
    )
    assert direct.status_code == 409, direct.text
    assert direct.json()["error"]["code"] == "QUOTATION_HAS_LIVE_PROFORMA"

    key = str(uuid4())
    payload = {"customer_po_number": "PO-1001", "customer_po_date": "2026-09-01"}
    converted = await client.post(
        f"/api/v1/proforma-invoices/{confirmed['id']}/convert-to-sales-order",
        headers=_idempotent(headers, confirmed["version"], key=key),
        json=payload,
    )
    assert converted.status_code == 200, converted.text
    order = converted.json()["data"]
    assert order["source_proforma_invoice_id"] == confirmed["id"]
    assert order["source_quotation_id"] == quote["id"]
    assert order["customer_po_number"] == "PO-1001"

    replay = await client.post(
        f"/api/v1/proforma-invoices/{confirmed['id']}/convert-to-sales-order",
        headers=_idempotent(headers, confirmed["version"], key=key),
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"]["id"] == order["id"]

    quote_after = await client.get(f"/api/v1/quotations/{quote['id']}", headers=headers)
    pfi_after = await client.get(f"/api/v1/proforma-invoices/{confirmed['id']}", headers=headers)
    assert quote_after.json()["data"]["status"] == "CONVERTED"
    assert quote_after.json()["data"]["converted_document_id"] == order["id"]
    assert pfi_after.json()["data"]["status"] == "CONVERTED"
    assert pfi_after.json()["data"]["converted_document_id"] == order["id"]


@pytest.mark.asyncio
async def test_second_pfi_is_blocked_while_first_is_live(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    quote = await _send_quote(client, headers, created["body"]["data"])
    first = await _raise_pfi(client, headers, quote)
    assert first["status"] == "DRAFT"
    fetched = await client.get(f"/api/v1/quotations/{quote['id']}", headers=headers)
    second = await client.post(
        f"/api/v1/quotations/{quote['id']}/convert-to-proforma-invoice",
        headers=_if_match(headers, fetched.json()["data"]["version"]),
    )
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "QUOTATION_HAS_LIVE_PROFORMA"


@pytest.mark.asyncio
async def test_convert_confirmed_pfi_to_sales_invoice(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    quote = await _send_quote(client, headers, created["body"]["data"])
    pfi = await _raise_pfi(client, headers, quote)
    confirmed = await _send_and_confirm_pfi(client, headers, pfi)
    converted = await client.post(
        f"/api/v1/proforma-invoices/{confirmed['id']}/convert-to-sales-invoice",
        headers=_idempotent(headers, confirmed["version"]),
    )
    assert converted.status_code == 200, converted.text
    invoice = converted.json()["data"]
    assert invoice["source_proforma_invoice_id"] == confirmed["id"]
    assert invoice["source_quotation_id"] == quote["id"]
    assert invoice["journal_entry_id"] is None
    assert "create_sales_invoice" in confirmed["available_actions"]

    pfi_after = await client.get(f"/api/v1/proforma-invoices/{confirmed['id']}", headers=headers)
    quote_after = await client.get(f"/api/v1/quotations/{quote['id']}", headers=headers)
    assert pfi_after.json()["data"]["status"] == "CONVERTED"
    assert pfi_after.json()["data"]["converted_document_type"] == "SALES_INVOICE"
    assert quote_after.json()["data"]["status"] == "CONVERTED"
    related_types = {
        item["document_type"] for item in pfi_after.json()["data"]["related_documents"]
    }
    assert "QUOTATION" in related_types
    assert "SALES_INVOICE" in related_types

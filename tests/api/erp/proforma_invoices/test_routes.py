"""API tests for proforma invoice lifecycle."""

from __future__ import annotations

from decimal import Decimal

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


@pytest.mark.asyncio
async def test_proforma_from_sent_quotation_keeps_quote_sent(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    quote = await _send_quote(client, headers, created["body"]["data"])
    pfi = await client.post(
        f"/api/v1/quotations/{quote['id']}/convert-to-proforma-invoice",
        headers=_if_match(headers, quote["version"]),
        json={"incoterm": "FOB"},
    )
    assert pfi.status_code == 200, pfi.text
    data = pfi.json()["data"]
    assert data["status"] == "DRAFT"
    assert data["source_quotation_id"] == quote["id"]
    assert data["display_number"] == data["document_number"]
    assert data["incoterm"] == "FOB"
    assert len(data["milestones"]) == 2
    assert Decimal(data["advance_required_amount"]) == Decimal("63.0000")
    assert data["lines"][0]["source_quotation_line_id"] == quote["lines"][0]["id"]

    fetched = await client.get(f"/api/v1/quotations/{quote['id']}", headers=headers)
    assert fetched.json()["data"]["status"] == "SENT"
    assert fetched.json()["data"]["converted_document_id"] is None

    listed = await client.get(
        f"/api/v1/proforma-invoices?source_quotation_id={quote['id']}",
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["data"][0]["id"] == data["id"]


@pytest.mark.asyncio
async def test_send_confirm_revise_and_clone(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    quote = await _send_quote(client, headers, created["body"]["data"])
    created_pfi = await client.post(
        f"/api/v1/quotations/{quote['id']}/convert-to-proforma-invoice",
        headers=_if_match(headers, quote["version"]),
    )
    pfi = created_pfi.json()["data"]
    updated = await client.patch(
        f"/api/v1/proforma-invoices/{pfi['id']}",
        headers=_if_match(headers, pfi["version"]),
        json={"notes": "LC against this PFI", "version": pfi["version"]},
    )
    assert updated.status_code == 200, updated.text
    sent = await client.post(
        f"/api/v1/proforma-invoices/{pfi['id']}/send",
        headers=_if_match(headers, updated.json()["data"]["version"]),
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["data"]["status"] == "SENT"
    assert sent.json()["data"]["sent_at"] is not None

    revised = await client.post(
        f"/api/v1/proforma-invoices/{pfi['id']}/revise",
        headers=_if_match(headers, sent.json()["data"]["version"]),
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["data"]["status"] == "DRAFT"

    resent = await client.post(
        f"/api/v1/proforma-invoices/{pfi['id']}/send",
        headers=_if_match(headers, revised.json()["data"]["version"]),
    )
    confirmed = await client.post(
        f"/api/v1/proforma-invoices/{pfi['id']}/confirm",
        headers=_if_match(headers, resent.json()["data"]["version"]),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["status"] == "CONFIRMED"

    cloned = await client.post(
        f"/api/v1/proforma-invoices/{pfi['id']}/clone",
        headers=headers,
    )
    assert cloned.status_code == 200, cloned.text
    assert cloned.json()["data"]["status"] == "DRAFT"
    assert cloned.json()["data"]["id"] != pfi["id"]


@pytest.mark.asyncio
async def test_decline_reopen_and_cancel(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    quote = await _send_quote(client, headers, created["body"]["data"])
    created_pfi = await client.post(
        f"/api/v1/quotations/{quote['id']}/convert-to-proforma-invoice",
        headers=_if_match(headers, quote["version"]),
    )
    pfi = created_pfi.json()["data"]
    sent = await client.post(
        f"/api/v1/proforma-invoices/{pfi['id']}/send",
        headers=_if_match(headers, pfi["version"]),
    )
    declined = await client.post(
        f"/api/v1/proforma-invoices/{pfi['id']}/decline",
        headers=_if_match(headers, sent.json()["data"]["version"]),
        json={"reason": "Customer walked away"},
    )
    assert declined.status_code == 200, declined.text
    assert declined.json()["data"]["status"] == "DECLINED"
    reopened = await client.post(
        f"/api/v1/proforma-invoices/{pfi['id']}/reopen",
        headers=_if_match(headers, declined.json()["data"]["version"]),
    )
    assert reopened.json()["data"]["status"] == "DRAFT"
    cancelled = await client.post(
        f"/api/v1/proforma-invoices/{pfi['id']}/cancel",
        headers=_if_match(headers, reopened.json()["data"]["version"]),
        json={"reason": "No longer needed"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["status"] == "CANCELLED"

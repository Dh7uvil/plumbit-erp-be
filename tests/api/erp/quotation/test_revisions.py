"""API tests for quotation revisions."""

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


@pytest.mark.asyncio
async def test_revise_from_sent_snapshots_and_rewinds(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    quote = await _send_quote(client, headers, created["body"]["data"])
    assert quote["display_number"] == quote["quote_number"]
    assert quote["revision_number"] == 0

    revised = await client.post(
        f"/api/v1/quotations/{quote['id']}/revise",
        headers=_if_match(headers, quote["version"]),
        json={"revision_reason": "Customer asked for a better price"},
    )
    assert revised.status_code == 200, revised.text
    data = revised.json()["data"]
    assert data["status"] == "DRAFT"
    assert data["revision_number"] == 1
    assert data["revision_count"] == 1
    assert data["display_number"] == f"{quote['quote_number']}-R1"
    assert data["quote_number"] == quote["quote_number"]

    listed = await client.get(f"/api/v1/quotations/{quote['id']}/revisions", headers=headers)
    assert listed.status_code == 200, listed.text
    items = listed.json()["data"]
    assert len(items) == 1
    assert items[0]["revision_number"] == 1
    assert items[0]["status_at_revision"] == "SENT"
    assert items[0]["revision_reason"] == "Customer asked for a better price"

    snapshot = await client.get(f"/api/v1/quotations/{quote['id']}/revisions/1", headers=headers)
    assert snapshot.status_code == 200, snapshot.text
    body = snapshot.json()["data"]
    assert body["header"]["quote_number"] == quote["quote_number"]
    assert body["lines"][0]["product_sku"] is not None


@pytest.mark.asyncio
async def test_revise_refused_once_converted(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    sent = await _send_quote(client, headers, created["body"]["data"])
    accepted = await client.post(
        f"/api/v1/quotations/{sent['id']}/accept",
        headers=_if_match(headers, sent["version"]),
    )
    assert accepted.status_code == 200, accepted.text
    quote = accepted.json()["data"]
    converted = await client.post(
        f"/api/v1/quotations/{quote['id']}/convert-to-sales-order",
        headers=_idempotent(headers, quote["version"]),
    )
    assert converted.status_code == 200, converted.text
    fetched = await client.get(f"/api/v1/quotations/{quote['id']}", headers=headers)
    refused = await client.post(
        f"/api/v1/quotations/{quote['id']}/revise",
        headers=_if_match(headers, fetched.json()["data"]["version"]),
        json={"revision_reason": "Too late"},
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


@pytest.mark.asyncio
async def test_revise_refused_with_live_proforma(client: AsyncClient) -> None:
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
    )
    assert pfi.status_code == 200, pfi.text
    fetched = await client.get(f"/api/v1/quotations/{quote['id']}", headers=headers)
    refused = await client.post(
        f"/api/v1/quotations/{quote['id']}/revise",
        headers=_if_match(headers, fetched.json()["data"]["version"]),
        json={"revision_reason": "Supersede the live PFI"},
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "QUOTATION_HAS_LIVE_PROFORMA"

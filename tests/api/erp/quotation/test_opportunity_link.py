"""Quotation behaviour with optional opportunity_id."""

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

)
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_quotation_create_approve_and_revise_without_opportunity_id(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers, currency_id=ids["aed"])
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(
        client,
        headers,
        customer_id=customer_id,
        product_id=product_id,
        currency_id=ids["aed"],
    )
    assert created["status_code"] == 201, created["text"]
    quote = created["body"]["data"]
    assert quote.get("opportunity_id") in (None,)

    submitted = await client.post(
        f"/api/v1/quotations/{quote['id']}/submit",
        headers=_if_match(headers, quote["version"]),
    )
    assert submitted.status_code == 200, submitted.text
    approved = await client.post(
        f"/api/v1/quotations/{quote['id']}/approve",
        headers=_if_match(headers, submitted.json()["data"]["version"]),
    )
    assert approved.status_code == 200, approved.text
    sent_response = await client.post(
        f"/api/v1/quotations/{quote['id']}/send",
        headers=_if_match(headers, approved.json()["data"]["version"]),
    )
    assert sent_response.status_code == 200, sent_response.text
    sent = sent_response.json()["data"]
    revised = await client.post(
        f"/api/v1/quotations/{sent['id']}/revise",
        headers=_if_match(headers, sent["version"]),
        json={"revision_reason": "Updated pricing"},
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["data"]["revision_number"] >= 1


@pytest.mark.asyncio
async def test_quotation_create_with_opportunity_id(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    suffix = uuid4().hex[:6]
    lead = await client.post(
        "/api/v1/leads",
        headers=headers,
        json={"company_name": f"Quote Opp {suffix}"},
    )
    assert lead.status_code == 201, lead.text
    lead_row = lead.json()["data"]
    converted = await client.post(
        f"/api/v1/leads/{lead_row['id']}/convert",
        headers={
            **headers,
            "Idempotency-Key": str(uuid4()),
            "If-Match": str(lead_row["version"]),
        },
        json={
            "new_customer": {"name": f"Quote Opp {suffix}"},
            "contact": {"name": "Buyer", "is_primary": True},
            "opportunity": {"create": True, "name": f"Deal {suffix}"},
        },
    )
    assert converted.status_code == 201, converted.text
    conversion = converted.json()["data"]
    customer_id = conversion["customer_id"]
    opportunity_id = conversion["opportunity_id"]
    assert opportunity_id

    product_id = await _create_product(client, headers, ids)
    created = await client.post(
        "/api/v1/quotations",
        headers=headers,
        json={
            "customer_id": customer_id,
            "opportunity_id": opportunity_id,
            "currency_id": ids["aed"],
            "lines": [{"product_id": product_id, "quantity": "1"}],
        },
    )
    assert created.status_code == 201, created.text
    quotation = created.json()["data"]
    assert quotation["opportunity_id"] == opportunity_id

    listed = await client.get(
        f"/api/v1/opportunities/{opportunity_id}/quotations",
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    rows = listed.json()["data"]
    assert len(rows) == 1
    assert rows[0]["id"] == quotation["id"]

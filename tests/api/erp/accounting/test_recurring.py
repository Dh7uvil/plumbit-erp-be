"""Recurring templates create drafts and never post them."""

from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient

from tests.api.erp.quotation.test_routes import _create_customer, _create_product, _seeded_ids
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_recurring_generates_a_draft_once(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    today = date.today().isoformat()
    created = await client.post(
        "/api/v1/recurring-templates",
        headers=headers,
        json={
            "name": "Monthly retainer",
            "document_kind": "SALES_INVOICE",
            "frequency": "MONTHLY",
            "next_run_date": today,
            "max_occurrences": 1,
            "template_payload": {
                "customer_id": customer_id,
                "lines": [{"product_id": product_id, "quantity": "1"}],
            },
        },
    )
    assert created.status_code == 201, created.text
    template = created.json()["data"]
    generated = await client.post(
        f"/api/v1/recurring-templates/{template['id']}/generate",
        headers={**headers, "If-Match": str(template["version"])},
    )
    assert generated.status_code == 200, generated.text
    body = generated.json()["data"]
    assert body["status"] == "COMPLETED"
    assert body["occurrences_generated"] == 1
    assert len(body["generations"]) == 1
    invoice_id = body["generations"][0]["document_id"]
    invoice = await client.get(f"/api/v1/sales-invoices/{invoice_id}", headers=headers)
    assert invoice.status_code == 200, invoice.text
    draft = invoice.json()["data"]
    assert draft["status"] == "DRAFT"
    assert draft["is_posted"] is False
    again = await client.post(
        f"/api/v1/recurring-templates/{template['id']}/generate",
        headers={**headers, "If-Match": str(body["version"])},
    )
    assert again.status_code == 422, again.text
    listed = await client.get("/api/v1/sales-invoices?page_size=20", headers=headers)
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["data"]) == 1


@pytest.mark.asyncio
async def test_recurring_template_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    ids = await _seeded_ids(client, headers_a)
    customer_id = await _create_customer(client, headers_a)
    product_id = await _create_product(client, headers_a, ids)
    created = await client.post(
        "/api/v1/recurring-templates",
        headers=headers_a,
        json={
            "name": "Private",
            "document_kind": "SALES_INVOICE",
            "frequency": "MONTHLY",
            "next_run_date": date.today().isoformat(),
            "template_payload": {
                "customer_id": customer_id,
                "lines": [{"product_id": product_id, "quantity": "1"}],
            },
        },
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["data"]["id"]
    cross = await client.get(f"/api/v1/recurring-templates/{template_id}", headers=headers_b)
    assert cross.status_code == 404, cross.text

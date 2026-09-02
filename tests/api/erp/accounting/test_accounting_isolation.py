"""Tenant isolation for accounting masters."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _assert_isolated(
    client: AsyncClient,
    headers_b: dict[str, str],
    collection: str,
    item_id: str,
) -> None:
    fetched = await client.get(f"/api/v1/{collection}/{item_id}", headers=headers_b)
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    listed = await client.get(f"/api/v1/{collection}", headers=headers_b)
    assert listed.status_code == 200
    assert all(item["id"] != item_id for item in listed.json()["data"])


@pytest.mark.asyncio
async def test_tax_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    listed = await client.get("/api/v1/taxes?page_size=100", headers=headers_a)
    assert listed.status_code == 200, listed.text
    tax_id = listed.json()["data"][0]["id"]
    await _assert_isolated(client, headers_b, "taxes", tax_id)


@pytest.mark.asyncio
async def test_payment_term_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    suffix = uuid4().hex[:8]
    created = await client.post(
        "/api/v1/payment-terms",
        headers=headers_a,
        json={"name": f"Net {suffix}", "days": 14},
    )
    assert created.status_code == 201, created.text
    await _assert_isolated(client, headers_b, "payment-terms", created.json()["data"]["id"])


@pytest.mark.asyncio
async def test_terms_template_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    suffix = uuid4().hex[:8]
    created = await client.post(
        "/api/v1/terms-templates",
        headers=headers_a,
        json={"name": f"Terms {suffix}", "body": "Payment due on receipt."},
    )
    assert created.status_code == 201, created.text
    await _assert_isolated(client, headers_b, "terms-templates", created.json()["data"]["id"])


@pytest.mark.asyncio
async def test_document_sequence_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    listed = await client.get("/api/v1/document-sequences?page_size=100", headers=headers_a)
    assert listed.status_code == 200, listed.text
    sequence_id = listed.json()["data"][0]["id"]
    await _assert_isolated(client, headers_b, "document-sequences", sequence_id)

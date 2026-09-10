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


@pytest.mark.asyncio
async def test_account_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    listed = await client.get("/api/v1/accounts?page_size=100", headers=headers_a)
    assert listed.status_code == 200, listed.text
    account_id = listed.json()["data"][0]["id"]
    await _assert_isolated(client, headers_b, "accounts", account_id)


@pytest.mark.asyncio
async def test_journal_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers_a)
    mapped = {item["role"]: item["account_id"] for item in roles.json()["data"]}
    created = await client.post(
        "/api/v1/journals",
        headers=headers_a,
        json={
            "lines": [
                {"account_id": mapped["BANK"], "debit": "10.0000", "credit": "0"},
                {"account_id": mapped["CASH_ON_HAND"], "debit": "0", "credit": "10.0000"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    await _assert_isolated(client, headers_b, "journals", created.json()["data"]["id"])


@pytest.mark.asyncio
async def test_opening_balances_state_is_tenant_scoped(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers_a)
    mapped = {item["role"]: item["account_id"] for item in roles.json()["data"]}
    from datetime import UTC, datetime, timedelta

    books_start = datetime.now(UTC).date() + timedelta(days=1)
    committed = await client.post(
        "/api/v1/opening-balances/commit",
        headers={**headers_a, "Idempotency-Key": uuid4().hex},
        json={
            "books_start_date": books_start.isoformat(),
            "gl_lines": [{"account_id": mapped["BANK"], "debit": "5.0000", "credit": "0"}],
        },
    )
    assert committed.status_code == 200, committed.text
    other = await client.get("/api/v1/opening-balances", headers=headers_b)
    assert other.status_code == 200, other.text
    assert other.json()["data"]["committed"] is False

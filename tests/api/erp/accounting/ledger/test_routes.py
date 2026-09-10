"""API tests for journal posting invariants."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


def _if_match(
    headers: dict[str, str], version: object, *, key: str | None = None
) -> dict[str, str]:
    extra = {**headers, "If-Match": str(version)}
    if key is not None:
        extra["Idempotency-Key"] = key
    return extra


async def _accounts(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    assert roles.status_code == 200, roles.text
    return {item["role"]: item["account_id"] for item in roles.json()["data"]}


async def _customer(client: AsyncClient, headers: dict[str, str]) -> str:
    suffix = uuid4().hex[:8]
    response = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "name": f"Customer {suffix}",
            "code": f"C-{suffix}",
            "tax_treatment": "UNREGISTERED",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


@pytest.mark.asyncio
async def test_balanced_journal_posts(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "narration": "Bank transfer",
            "lines": [
                {"account_id": accounts["BANK"], "debit": "100.0000", "credit": "0"},
                {"account_id": accounts["CASH_ON_HAND"], "debit": "0", "credit": "100.0000"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    posted = await client.post(
        f"/api/v1/journals/{row['id']}/post",
        headers=_if_match(headers, row["version"], key=uuid4().hex),
    )
    assert posted.status_code == 200, posted.text
    body = posted.json()["data"]
    assert body["status"] == "POSTED"
    assert body["is_posted"] is True
    assert body["total_debit_base"] == "100.0000"
    assert body["total_credit_base"] == "100.0000"


@pytest.mark.asyncio
async def test_unbalanced_journal_is_refused(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "lines": [
                {"account_id": accounts["BANK"], "debit": "100.0000", "credit": "0"},
                {"account_id": accounts["CASH_ON_HAND"], "debit": "0", "credit": "40.0000"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    posted = await client.post(
        f"/api/v1/journals/{row['id']}/post",
        headers=_if_match(headers, row["version"], key=uuid4().hex),
    )
    assert posted.status_code == 422, posted.text
    assert posted.json()["error"]["code"] == "JOURNAL_UNBALANCED"


@pytest.mark.asyncio
async def test_ar_line_without_party_is_refused(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "lines": [
                {"account_id": accounts["ACCOUNTS_RECEIVABLE"], "debit": "50.0000", "credit": "0"},
                {"account_id": accounts["SALES_REVENUE"], "debit": "0", "credit": "50.0000"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    posted = await client.post(
        f"/api/v1/journals/{row['id']}/post",
        headers=_if_match(headers, row["version"], key=uuid4().hex),
    )
    assert posted.status_code == 422, posted.text
    assert posted.json()["error"]["code"] == "PARTY_REQUIRED_FOR_CONTROL_ACCOUNT"


@pytest.mark.asyncio
async def test_posted_journal_cannot_be_patched_and_reverse_creates_mirror(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "lines": [
                {"account_id": accounts["BANK"], "debit": "25.0000", "credit": "0"},
                {"account_id": accounts["CASH_ON_HAND"], "debit": "0", "credit": "25.0000"},
            ],
        },
    )
    row = created.json()["data"]
    posted = await client.post(
        f"/api/v1/journals/{row['id']}/post",
        headers=_if_match(headers, row["version"], key=uuid4().hex),
    )
    assert posted.status_code == 200, posted.text
    body = posted.json()["data"]
    patched = await client.patch(
        f"/api/v1/journals/{body['id']}",
        headers=_if_match(headers, body["version"]),
        json={"narration": "nope", "version": body["version"]},
    )
    assert patched.status_code == 409, patched.text
    reversed_row = await client.post(
        f"/api/v1/journals/{body['id']}/reverse",
        headers=_if_match(headers, body["version"], key=uuid4().hex),
        json={"reason": "Correction of posted cash transfer", "version": body["version"]},
    )
    assert reversed_row.status_code == 200, reversed_row.text
    mirror = reversed_row.json()["data"]
    assert mirror["journal_type"] == "REVERSAL"
    assert mirror["reversal_of_id"] == body["id"]
    assert mirror["status"] == "POSTED"
    original = await client.get(f"/api/v1/journals/{body['id']}", headers=headers)
    assert original.json()["data"]["reversed_by_id"] == mirror["id"]


@pytest.mark.asyncio
async def test_ar_line_with_party_posts(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    customer_id = await _customer(client, headers)
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "lines": [
                {
                    "account_id": accounts["ACCOUNTS_RECEIVABLE"],
                    "debit": "80.0000",
                    "credit": "0",
                    "party_type": "CUSTOMER",
                    "party_id": customer_id,
                    "due_date": "2026-10-01",
                    "external_reference": "INV-OPEN-1",
                },
                {"account_id": accounts["SALES_REVENUE"], "debit": "0", "credit": "80.0000"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    posted = await client.post(
        f"/api/v1/journals/{row['id']}/post",
        headers=_if_match(headers, row["version"], key=uuid4().hex),
    )
    assert posted.status_code == 200, posted.text


@pytest.mark.asyncio
async def test_group_account_cannot_be_posted_to(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    listed = await client.get("/api/v1/accounts?is_group=true&page_size=100", headers=headers)
    group = next(item for item in listed.json()["data"] if item["code"] == "1000")
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "lines": [
                {"account_id": group["id"], "debit": "10.0000", "credit": "0"},
                {"account_id": accounts["CASH_ON_HAND"], "debit": "0", "credit": "10.0000"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    posted = await client.post(
        f"/api/v1/journals/{row['id']}/post",
        headers=_if_match(headers, row["version"], key=uuid4().hex),
    )
    assert posted.status_code == 422, posted.text
    assert posted.json()["error"]["code"] == "ACCOUNT_NOT_POSTABLE"

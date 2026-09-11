"""API tests for the per-record activity feed."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.quotation.test_routes import (
    _create_customer,
    _create_product,
    _create_quote,
    _seeded_ids,
)
from tests.api.inventory_management.stock.test_stock_routes import _user_headers
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_quotation_activity_requires_quotation_read(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    assert created["status_code"] == 201, created["text"]
    quote_id = created["body"]["data"]["id"]

    reader = await _user_headers(client, headers, tenant_id, codes=("sales.quotation.read",))
    listed = await client.get(
        "/api/v1/activity",
        headers=reader,
        params={"entity_type": "quotation", "entity_id": quote_id},
    )
    assert listed.status_code == 200, listed.text
    actions = {item["action"] for item in listed.json()["data"]}
    assert "CREATE" in actions
    assert all("password" not in str(item.get("changed_fields")) for item in listed.json()["data"])

    customer_only = await _user_headers(client, headers, tenant_id, codes=("crm.customer.read",))
    denied = await client.get(
        "/api/v1/activity",
        headers=customer_only,
        params={"entity_type": "quotation", "entity_id": quote_id},
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_activity_unregistered_entity_type_is_validation_error(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    response = await client.get(
        "/api/v1/activity",
        headers=headers,
        params={"entity_type": "lead", "entity_id": str(uuid4())},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_activity_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    ids = await _seeded_ids(client, headers_a)
    customer_id = await _create_customer(client, headers_a)
    product_id = await _create_product(client, headers_a, ids)
    created = await _create_quote(client, headers_a, customer_id=customer_id, product_id=product_id)
    assert created["status_code"] == 201, created["text"]
    quote_id = created["body"]["data"]["id"]

    listed = await client.get(
        "/api/v1/activity",
        headers=headers_b,
        params={"entity_type": "quotation", "entity_id": quote_id},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["data"] == []
    assert listed.json()["meta"]["total"] == 0

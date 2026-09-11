"""Credit-limit WARN / BLOCK / unlimited on sales-order confirm."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.sales_orders.test_routes import (
    _create_customer,
    _create_order,
    _create_product,
    _seeded_ids,
)
from tests.conftest import login_headers, provision_admin


def _if_match(headers: dict[str, str], version: object) -> dict[str, str]:
    return {**headers, "If-Match": str(version)}


@pytest.mark.asyncio
async def test_null_credit_limit_confirm_is_untouched(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_order(client, headers, customer_id=customer_id, product_id=product_id)
    assert created["status_code"] == 201, created["text"]
    order = created["body"]["data"]
    confirmed = await client.post(
        f"/api/v1/sales-orders/{order['id']}/confirm",
        headers=_if_match(headers, order["version"]),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["warnings"] == []


@pytest.mark.asyncio
async def test_block_policy_refuses_confirm_without_override(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    updated = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"credit_limit_policy": "BLOCK"},
    )
    assert updated.status_code == 200, updated.text
    ids = await _seeded_ids(client, headers)
    suffix = uuid4().hex[:8]
    customer = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "name": f"Limited {suffix}",
            "code": f"C-{suffix}",
            "tax_treatment": "REGISTERED",
            "trn": "100000000000003",
            "credit_limit": "50.0000",
            "shipping_address": {
                "address_line_1": "Warehouse 1",
                "city": "Dubai",
                "state": "DUBAI",
                "country_code": "AE",
                "country": "United Arab Emirates",
            },
            "billing_address": {
                "address_line_1": "Office 1",
                "city": "Dubai",
                "state": "DUBAI",
                "country_code": "AE",
                "country": "United Arab Emirates",
            },
        },
    )
    assert customer.status_code == 201, customer.text
    product_id = await _create_product(client, headers, ids)
    created = await _create_order(
        client, headers, customer_id=customer.json()["data"]["id"], product_id=product_id
    )
    order = created["body"]["data"]
    blocked = await client.post(
        f"/api/v1/sales-orders/{order['id']}/confirm",
        headers=_if_match(headers, order["version"]),
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "CREDIT_LIMIT_EXCEEDED"
    overridden = await client.post(
        f"/api/v1/sales-orders/{order['id']}/confirm",
        headers={
            **_if_match(headers, order["version"]),
            "X-Credit-Override": "Approved by credit manager",
        },
    )
    assert overridden.status_code == 200, overridden.text
    warnings = overridden.json()["data"]["warnings"]
    assert warnings
    assert warnings[0]["code"] == "CREDIT_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_warn_policy_confirms_with_warning(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    suffix = uuid4().hex[:8]
    customer = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "name": f"Warned {suffix}",
            "code": f"C-{suffix}",
            "tax_treatment": "REGISTERED",
            "trn": "100000000000003",
            "credit_limit": "10.0000",
            "shipping_address": {
                "address_line_1": "Warehouse 1",
                "city": "Dubai",
                "state": "DUBAI",
                "country_code": "AE",
                "country": "United Arab Emirates",
            },
            "billing_address": {
                "address_line_1": "Office 1",
                "city": "Dubai",
                "state": "DUBAI",
                "country_code": "AE",
                "country": "United Arab Emirates",
            },
        },
    )
    assert customer.status_code == 201, customer.text
    product_id = await _create_product(client, headers, ids)
    created = await _create_order(
        client, headers, customer_id=customer.json()["data"]["id"], product_id=product_id
    )
    order = created["body"]["data"]
    assert Decimal(order["grand_total"]) > Decimal("10.0000")
    confirmed = await client.post(
        f"/api/v1/sales-orders/{order['id']}/confirm",
        headers=_if_match(headers, order["version"]),
    )
    assert confirmed.status_code == 200, confirmed.text
    warnings = confirmed.json()["data"]["warnings"]
    assert warnings
    assert warnings[0]["code"] == "CREDIT_LIMIT_EXCEEDED"

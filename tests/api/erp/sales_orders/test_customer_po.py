"""API tests for customer PO capture and acknowledgement."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.api.erp.sales_orders.test_routes import (
    _create_customer,
    _create_product,
    _if_match,
    _seeded_ids,
)
from tests.conftest import login_headers, provision_admin


async def _create_order(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    customer_id: str,
    product_id: str,
    customer_po_number: str | None = "PO-7788",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "customer_id": customer_id,
        "lines": [{"product_id": product_id, "quantity": "2"}],
    }
    if customer_po_number is not None:
        payload["customer_po_number"] = customer_po_number
        payload["customer_po_date"] = "2026-09-01"
    response = await client.post("/api/v1/sales-orders", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _confirm(
    client: AsyncClient, headers: dict[str, str], order: dict[str, object]
) -> dict[str, object]:
    confirmed = await client.post(
        f"/api/v1/sales-orders/{order['id']}/confirm",
        headers=_if_match(headers, order["version"]),
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()["data"]


@pytest.mark.asyncio
async def test_acknowledge_requires_confirmed_order_with_customer_po(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)

    draft = await _create_order(client, headers, customer_id=customer_id, product_id=product_id)
    too_early = await client.post(
        f"/api/v1/sales-orders/{draft['id']}/acknowledge",
        headers=_if_match(headers, draft["version"]),
    )
    assert too_early.status_code == 409, too_early.text
    assert too_early.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"

    no_po = await _create_order(
        client,
        headers,
        customer_id=customer_id,
        product_id=product_id,
        customer_po_number=None,
    )
    confirmed_no_po = await _confirm(client, headers, no_po)
    missing_po = await client.post(
        f"/api/v1/sales-orders/{confirmed_no_po['id']}/acknowledge",
        headers=_if_match(headers, confirmed_no_po["version"]),
    )
    assert missing_po.status_code == 422, missing_po.text
    assert missing_po.json()["error"]["code"] == "CUSTOMER_PO_REQUIRED"

    confirmed = await _confirm(client, headers, draft)
    assert "acknowledge" in confirmed["available_actions"]
    acked = await client.post(
        f"/api/v1/sales-orders/{confirmed['id']}/acknowledge",
        headers=_if_match(headers, confirmed["version"]),
    )
    assert acked.status_code == 200, acked.text
    data = acked.json()["data"]
    assert data["status"] == "CONFIRMED"
    assert data["acknowledged_at"] is not None
    assert data["acknowledged_by"] is not None
    assert "acknowledge" not in data["available_actions"]

    again = await client.post(
        f"/api/v1/sales-orders/{data['id']}/acknowledge",
        headers=_if_match(headers, data["version"]),
    )
    assert again.status_code == 409, again.text
    assert again.json()["error"]["code"] == "ALREADY_ACKNOWLEDGED"


@pytest.mark.asyncio
async def test_duplicate_customer_po_warns_without_blocking(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    first = await _create_order(client, headers, customer_id=customer_id, product_id=product_id)
    second = await _create_order(client, headers, customer_id=customer_id, product_id=product_id)
    assert second["id"] != first["id"]
    assert second["customer_po_number"] == "PO-7788"

    check = await client.get(
        "/api/v1/sales-orders/check-customer-po",
        headers=headers,
        params={
            "customer_id": customer_id,
            "customer_po_number": "PO-7788",
            "exclude_id": second["id"],
        },
    )
    assert check.status_code == 200, check.text
    matches = check.json()["data"]
    assert len(matches) == 1
    assert matches[0]["id"] == first["id"]
    assert matches[0]["customer_po_number"] == "PO-7788"

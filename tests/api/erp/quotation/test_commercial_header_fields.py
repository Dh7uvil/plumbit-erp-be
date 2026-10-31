"""Round-trip commercial header fields on quotations."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _create_customer(client: AsyncClient, headers: dict[str, str]) -> str:
    suffix = uuid4().hex[:8]
    response = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "name": f"Commercial Customer {suffix}",
            "tax_treatment": "REGISTERED",
            "trn": f"{int(uuid4().int % (10**15 - 1)) + 1:015d}",
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
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


@pytest.mark.asyncio
async def test_quotation_commercial_header_fields_round_trip(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    customer_id = await _create_customer(client, headers)

    create_body = {
        "customer_id": customer_id,
        "payment_mode": "CASH",
        "reference_number": "REF-COMM-1",
        "marks": "Handle with care",
        "price_basis": "PRICE_1",
        "fiscal_period": 7,
        "lines": [
            {
                "description": "Consulting",
                "quantity": "1",
                "rate": "100",
            }
        ],
    }
    create_resp = await client.post(
        "/api/v1/quotations",
        json=create_body,
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()["data"]
    assert created["payment_mode"] == "CASH"
    assert created["reference_number"] == "REF-COMM-1"
    assert created["marks"] == "Handle with care"
    assert created["price_basis"] == "PRICE_1"
    assert created["fiscal_period"] == 7
    assert created["registration_type"] is not None

    quotation_id = created["id"]
    patch_resp = await client.patch(
        f"/api/v1/quotations/{quotation_id}",
        json={
            "payment_mode": "CREDIT",
            "marks": "Updated marks",
            "version": created["version"],
        },
        headers=headers,
    )
    assert patch_resp.status_code == 200, patch_resp.text
    updated = patch_resp.json()["data"]
    assert updated["payment_mode"] == "CREDIT"
    assert updated["marks"] == "Updated marks"
    assert Decimal(updated["grand_total"]) >= Decimal("0")

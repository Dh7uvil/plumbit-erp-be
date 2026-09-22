"""Landed cost guards for expensed charge types."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.api.erp.landed_costs.test_routes import (
    _create_from_po,
    _create_product,
    _create_supplier,
    _idempotent,
    _if_match,
    _post_grn,
    _seeded_ids,
)
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_expensed_charge_cannot_allocate_to_landed_cost(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    supplier_id = await _create_supplier(client, headers)
    charge_types = await client.get("/api/v1/charge-types?search=BANK", headers=headers)
    bank = next(row for row in charge_types.json()["data"] if row["code"] == "BANK_CHARGES")
    created = await client.post(
        "/api/v1/purchase-invoices",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "bill_type": "EXPENSE",
            "lines": [
                {
                    "line_type": "EXPENSE",
                    "description": "Bank fee",
                    "quantity": "1",
                    "rate": "15.0000",
                    "charge_type_id": bank["id"],
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    bill = created.json()["data"]
    posted = await client.post(
        f"/api/v1/purchase-invoices/{bill['id']}/post",
        headers=_idempotent(headers, bill["version"]),
    )
    assert posted.status_code == 200, posted.text
    line_id = posted.json()["data"]["lines"][0]["id"]

    ids = await _seeded_ids(client, headers)
    product_id = await _create_product(
        client, headers, ids, track_inventory=True, purchase_rate="10.0000"
    )
    po = await client.post(
        "/api/v1/purchase-orders",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "lines": [{"product_id": product_id, "quantity": "1", "rate": "10.0000"}],
        },
    )
    assert po.status_code == 201, po.text
    issued = await client.post(
        f"/api/v1/purchase-orders/{po.json()['data']['id']}/issue",
        headers=_if_match(headers, po.json()["data"]["version"]),
    )
    receipt = await _create_from_po(client, headers, issued.json()["data"]["id"])
    posted_grn = await _post_grn(
        client, headers, receipt["body"]["data"]["id"], receipt["body"]["data"]["version"]
    )
    grn = posted_grn.json()["data"]

    lc = await client.post(
        "/api/v1/landed-costs",
        headers=headers,
        json={
            "allocation_method": "VALUE",
            "charges": [{"purchase_invoice_line_id": line_id}],
            "allocations": [{"goods_receipt_line_id": grn["lines"][0]["id"]}],
        },
    )
    assert lc.status_code == 422, lc.text
    assert "Expensed charges" in lc.json()["error"]["message"]

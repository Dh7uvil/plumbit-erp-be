"""API tests for import/export cost sheets."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.api.erp.purchase_orders.test_routes import (
    _create_product,
    _create_supplier,
    _if_match,
    _seeded_ids,
)
from tests.api.erp.sales_orders.test_routes import _create_customer
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_create_import_cost_sheet_with_computed_totals(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    supplier_id = await _create_supplier(client, headers)
    ids = await _seeded_ids(client, headers)
    product_id = await _create_product(
        client, headers, ids, track_inventory=True, purchase_rate="100.0000"
    )
    freight = await client.get("/api/v1/charge-types?search=FREIGHT", headers=headers)
    freight_row = freight.json()["data"][0]
    created = await client.post(
        "/api/v1/cost-sheets",
        headers=headers,
        json={
            "sheet_type": "IMPORT",
            "supplier_id": supplier_id,
            "lines": [
                {
                    "product_id": product_id,
                    "unit_id": ids["pcs"],
                    "quantity": "10",
                    "base_rate": "100.0000",
                }
            ],
            "charges": [
                {"charge_type_id": freight_row["id"], "estimated_amount": "500.0000"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()["data"]
    assert body["sheet_type"] == "IMPORT"
    assert body["status"] == "DRAFT"
    assert body["document_number"].startswith("CSI")
    assert body["totals"]["goods_value_estimated"] == "1000.0000"
    assert body["totals"]["inventoriable_charges_estimated"] == "500.0000"
    assert body["lines"][0]["estimated_landed_unit_cost"] == "150.0000"
    assert "confirm" in body["available_actions"]


@pytest.mark.asyncio
async def test_cost_sheet_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    customer_id = await _create_customer(client, headers_a)
    ids = await _seeded_ids(client, headers_a)
    product_id = await _create_product(client, headers_a, ids, track_inventory=True)
    created = await client.post(
        "/api/v1/cost-sheets",
        headers=headers_a,
        json={
            "sheet_type": "EXPORT",
            "customer_id": customer_id,
            "lines": [
                {
                    "product_id": product_id,
                    "unit_id": ids["pcs"],
                    "quantity": "1",
                    "base_rate": "10.0000",
                    "target_selling_price": "15.0000",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    sheet_id = created.json()["data"]["id"]
    cross = await client.get(f"/api/v1/cost-sheets/{sheet_id}", headers=headers_b)
    assert cross.status_code == 404, cross.text


@pytest.mark.asyncio
async def test_create_other_cost_sheet(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    product_id = await _create_product(client, headers, ids, track_inventory=True)
    created = await client.post(
        "/api/v1/cost-sheets",
        headers=headers,
        json={
            "sheet_type": "OTHER",
            "lines": [
                {
                    "product_id": product_id,
                    "unit_id": ids["pcs"],
                    "quantity": "1",
                    "base_rate": "25.0000",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["sheet_type"] == "OTHER"
    assert created.json()["data"]["document_number"].startswith("CSO")


@pytest.mark.asyncio
async def test_confirm_cost_sheet(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    supplier_id = await _create_supplier(client, headers)
    ids = await _seeded_ids(client, headers)
    product_id = await _create_product(client, headers, ids, track_inventory=True)
    created = await client.post(
        "/api/v1/cost-sheets",
        headers=headers,
        json={
            "sheet_type": "IMPORT",
            "supplier_id": supplier_id,
            "lines": [
                {
                    "product_id": product_id,
                    "unit_id": ids["pcs"],
                    "quantity": "2",
                    "base_rate": "50.0000",
                }
            ],
        },
    )
    sheet = created.json()["data"]
    confirmed = await client.post(
        f"/api/v1/cost-sheets/{sheet['id']}/confirm",
        headers=_if_match(headers, sheet["version"]),
        json={"version": sheet["version"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["status"] == "CONFIRMED"
    assert "reopen" in confirmed.json()["data"]["available_actions"]
    assert "close" in confirmed.json()["data"]["available_actions"]


async def _create_draft_sheet(client: AsyncClient, headers: dict[str, str]) -> dict:
    supplier_id = await _create_supplier(client, headers)
    ids = await _seeded_ids(client, headers)
    product_id = await _create_product(client, headers, ids, track_inventory=True)
    created = await client.post(
        "/api/v1/cost-sheets",
        headers=headers,
        json={
            "sheet_type": "IMPORT",
            "supplier_id": supplier_id,
            "allocation_method": "QUANTITY",
            "incoterm": "CIF",
            "lines": [
                {
                    "product_id": product_id,
                    "unit_id": ids["pcs"],
                    "quantity": "2",
                    "base_rate": "50.0000",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]


@pytest.mark.asyncio
async def test_reopen_and_close_cost_sheet(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    sheet = await _create_draft_sheet(client, headers)
    confirmed = await client.post(
        f"/api/v1/cost-sheets/{sheet['id']}/confirm",
        headers=_if_match(headers, sheet["version"]),
        json={"version": sheet["version"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()["data"]
    reopened = await client.post(
        f"/api/v1/cost-sheets/{body['id']}/reopen",
        headers=_if_match(headers, body["version"]),
        json={"version": body["version"]},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["data"]["status"] == "DRAFT"
    draft = reopened.json()["data"]
    confirmed_again = await client.post(
        f"/api/v1/cost-sheets/{draft['id']}/confirm",
        headers=_if_match(headers, draft["version"]),
        json={"version": draft["version"]},
    )
    assert confirmed_again.status_code == 200, confirmed_again.text
    confirmed_body = confirmed_again.json()["data"]
    closed = await client.post(
        f"/api/v1/cost-sheets/{confirmed_body['id']}/close",
        headers=_if_match(headers, confirmed_body["version"]),
        json={"version": confirmed_body["version"]},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["data"]["status"] == "CLOSED"
    assert "pull_actuals" not in closed.json()["data"]["available_actions"]


@pytest.mark.asyncio
async def test_delete_draft_cost_sheet(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    sheet = await _create_draft_sheet(client, headers)
    deleted = await client.delete(
        f"/api/v1/cost-sheets/{sheet['id']}",
        headers=_if_match(headers, sheet["version"]),
    )
    assert deleted.status_code == 200, deleted.text
    missing = await client.get(f"/api/v1/cost-sheets/{sheet['id']}", headers=headers)
    assert missing.status_code == 404, missing.text

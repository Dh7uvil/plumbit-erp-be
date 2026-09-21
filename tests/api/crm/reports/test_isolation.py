"""Tenant isolation for CRM reports."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_crm_report_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)

    pipelines = await client.get("/api/v1/pipelines", headers=headers_a)
    assert pipelines.status_code == 200, pipelines.text
    pipeline_id = pipelines.json()["data"][0]["id"]
    detail = await client.get(f"/api/v1/pipelines/{pipeline_id}", headers=headers_a)
    open_stage = next(
        stage for stage in detail.json()["data"]["stages"] if stage["stage_kind"] == "OPEN"
    )
    currencies = await client.get("/api/v1/currencies?is_base=true", headers=headers_a)
    currency_id = currencies.json()["data"][0]["id"]
    created = await client.post(
        "/api/v1/opportunities",
        headers=headers_a,
        json={
            "name": f"Iso {uuid4().hex[:8]}",
            "pipeline_id": pipeline_id,
            "stage_id": open_stage["id"],
            "amount": "500.0000",
            "currency_id": currency_id,
        },
    )
    assert created.status_code == 201, created.text

    other = await client.get(
        "/api/v1/reports/sales-pipeline",
        headers=headers_b,
        params={"pipeline_id": pipeline_id},
    )
    assert other.status_code == 404, other.text
    assert other.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    own = await client.get("/api/v1/reports/sales-pipeline", headers=headers_b)
    assert own.status_code == 200, own.text
    assert own.json()["data"]["opportunity_count"] == 0
    assert Decimal(str(own.json()["data"]["total_amount"])) == Decimal("0")

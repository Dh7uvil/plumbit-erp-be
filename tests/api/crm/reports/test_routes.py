"""API tests for CRM report routes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _open_stage(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    pipelines = await client.get("/api/v1/pipelines", headers=headers)
    assert pipelines.status_code == 200, pipelines.text
    pipeline_id = pipelines.json()["data"][0]["id"]
    detail = await client.get(f"/api/v1/pipelines/{pipeline_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    open_stage = next(
        stage for stage in detail.json()["data"]["stages"] if stage["stage_kind"] == "OPEN"
    )
    return pipeline_id, open_stage["id"]


async def _base_currency(client: AsyncClient, headers: dict[str, str]) -> str:
    currencies = await client.get("/api/v1/currencies?is_base=true", headers=headers)
    assert currencies.status_code == 200, currencies.text
    return currencies.json()["data"][0]["id"]


@pytest.mark.asyncio
async def test_crm_report_routes_and_csv(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    pipeline_id, stage_id = await _open_stage(client, headers)
    currency_id = await _base_currency(client, headers)
    created = await client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={
            "name": f"Pipeline {uuid4().hex[:6]}",
            "pipeline_id": pipeline_id,
            "stage_id": stage_id,
            "amount": "120.0000",
            "currency_id": currency_id,
            "probability": "25.0000",
            "expected_close_date": date.today().isoformat(),
        },
    )
    assert created.status_code == 201, created.text
    await client.post(
        "/api/v1/leads",
        headers=headers,
        json={"company_name": f"Report {uuid4().hex[:6]}"},
    )

    pipeline = await client.get(
        "/api/v1/reports/sales-pipeline",
        headers=headers,
        params={"pipeline_id": pipeline_id},
    )
    assert pipeline.status_code == 200, pipeline.text
    data = pipeline.json()["data"]
    assert data["opportunity_count"] >= 1
    assert Decimal(str(data["total_amount"])) >= Decimal("120")
    assert data["currency_code"]

    funnel = await client.get(
        "/api/v1/reports/sales-funnel",
        headers=headers,
        params={"pipeline_id": pipeline_id},
    )
    assert funnel.status_code == 200, funnel.text
    assert funnel.json()["data"]["pipeline_id"] == pipeline_id

    win_loss = await client.get(
        "/api/v1/reports/win-loss",
        headers=headers,
        params={"from": "2026-01-01", "to": "2026-12-31"},
    )
    assert win_loss.status_code == 200, win_loss.text

    conversion = await client.get(
        "/api/v1/reports/lead-conversion",
        headers=headers,
        params={"from": "2020-01-01", "to": "2030-01-01"},
    )
    assert conversion.status_code == 200, conversion.text
    assert conversion.json()["data"]["lead_count"] >= 1

    activity = await client.get(
        "/api/v1/reports/sales-activity",
        headers=headers,
        params={"from": "2020-01-01", "to": "2030-01-01"},
    )
    assert activity.status_code == 200, activity.text

    dashboard = await client.get("/api/v1/reports/crm-dashboard", headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["data"]["open_pipeline_count"] >= 1

    csv_body = await client.get(
        "/api/v1/reports/sales-pipeline",
        headers=headers,
        params={"pipeline_id": pipeline_id, "format": "csv"},
    )
    assert csv_body.status_code == 200, csv_body.text
    assert "text/csv" in csv_body.headers["content-type"]
    assert "opportunity_count" in csv_body.text


@pytest.mark.asyncio
async def test_crm_report_rejects_invalid_group_by(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    response = await client.get(
        "/api/v1/reports/sales-pipeline",
        headers=headers,
        params={"group_by": "not-a-group"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_crm_report_rejects_inverted_dates(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    response = await client.get(
        "/api/v1/reports/win-loss",
        headers=headers,
        params={"from": "2026-12-31", "to": "2026-01-01"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"

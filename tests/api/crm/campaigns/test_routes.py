"""API tests for campaign CRUD, members, and ROI."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _create_campaign(client: AsyncClient, headers: dict[str, str], **extra: object) -> dict:
    payload: dict[str, object] = {
        "name": f"Campaign {uuid4().hex[:8]}",
        "campaign_type": "EMAIL",
        "status": "ACTIVE",
        "actual_cost": "50.0000",
    }
    payload.update(extra)
    created = await client.post("/api/v1/campaigns", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    return created.json()["data"]


@pytest.mark.asyncio
async def test_campaign_crud_members_and_roi(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    row = await _create_campaign(client, headers)
    assert row["status"] == "ACTIVE"
    assert row["campaign_type"] == "EMAIL"

    listed = await client.get("/api/v1/campaigns", headers=headers, params={"status": "ACTIVE"})
    assert listed.status_code == 200, listed.text
    assert listed.json()["meta"]["total"] >= 1

    lead = await client.post(
        "/api/v1/leads",
        headers=headers,
        json={"company_name": f"Camp {uuid4().hex[:8]}", "campaign_id": row["id"]},
    )
    assert lead.status_code == 201, lead.text
    assert lead.json()["data"]["campaign_id"] == row["id"]

    member = await client.post(
        f"/api/v1/campaigns/{row['id']}/members",
        headers=headers,
        json={"member_type": "lead", "member_id": lead.json()["data"]["id"]},
    )
    assert member.status_code == 201, member.text
    assert member.json()["data"]["member_status"] == "PLANNED"

    duplicate = await client.post(
        f"/api/v1/campaigns/{row['id']}/members",
        headers=headers,
        json={"member_type": "lead", "member_id": lead.json()["data"]["id"]},
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["error"]["code"] == "DUPLICATE_RESOURCE"

    currencies = await client.get("/api/v1/currencies?is_base=true", headers=headers)
    assert currencies.status_code == 200, currencies.text
    currency_id = currencies.json()["data"][0]["id"]
    pipelines = await client.get("/api/v1/pipelines", headers=headers)
    assert pipelines.status_code == 200, pipelines.text
    pipeline_id = pipelines.json()["data"][0]["id"]
    detail = await client.get(f"/api/v1/pipelines/{pipeline_id}", headers=headers)
    open_stage = next(
        stage for stage in detail.json()["data"]["stages"] if stage["stage_kind"] == "OPEN"
    )
    opportunity = await client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={
            "name": f"Won from campaign {uuid4().hex[:6]}",
            "pipeline_id": pipeline_id,
            "stage_id": open_stage["id"],
            "amount": "150.0000",
            "currency_id": currency_id,
            "campaign_id": row["id"],
        },
    )
    assert opportunity.status_code == 201, opportunity.text
    won = await client.post(
        f"/api/v1/opportunities/{opportunity.json()['data']['id']}/win",
        headers={**headers, "If-Match": str(opportunity.json()["data"]["version"])},
        json={},
    )
    assert won.status_code == 200, won.text

    roi = await client.get(f"/api/v1/campaigns/{row['id']}/roi", headers=headers)
    assert roi.status_code == 200, roi.text
    data = roi.json()["data"]
    assert data["member_count"] == 1
    assert data["converted_leads"] == 0
    assert data["won_opportunity_count"] == 1
    assert Decimal(str(data["won_opportunity_value"])) == Decimal("150")
    assert Decimal(str(data["roi"])) == Decimal("200")

    patched = await client.patch(
        f"/api/v1/campaigns/{row['id']}",
        headers=headers,
        json={"name": f"Renamed {uuid4().hex[:6]}"},
    )
    assert patched.status_code == 200, patched.text


@pytest.mark.asyncio
async def test_campaign_rejects_inverted_dates(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    response = await client.post(
        "/api/v1/campaigns",
        headers=headers,
        json={
            "name": f"Bad dates {uuid4().hex[:6]}",
            "campaign_type": "WEBINAR",
            "start_date": "2026-09-21",
            "end_date": "2026-09-01",
        },
    )
    assert response.status_code == 422, response.text

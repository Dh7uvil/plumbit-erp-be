"""API tests for activity CRUD and complete."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _create_lead(client: AsyncClient, headers: dict[str, str]) -> str:
    created = await client.post(
        "/api/v1/leads",
        headers=headers,
        json={"company_name": f"Act {uuid4().hex[:8]}"},
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


@pytest.mark.asyncio
async def test_activity_crud_and_complete(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    lead_id = await _create_lead(client, headers)
    created = await client.post(
        "/api/v1/activities",
        headers=headers,
        json={
            "activity_type": "TASK",
            "subject": "Call prospect",
            "related_entity_type": "lead",
            "related_entity_id": lead_id,
            "priority": "HIGH",
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    assert row["status"] == "OPEN"
    assert row["activity_type"] == "TASK"
    assert "complete" in row["available_actions"]

    listed = await client.get(
        "/api/v1/activities",
        headers=headers,
        params={"related_entity_type": "lead", "related_entity_id": lead_id},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["meta"]["total"] == 1

    completed = await client.post(
        f"/api/v1/activities/{row['id']}/complete",
        headers=headers,
        json={"outcome": "Left voicemail"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["data"]["status"] == "COMPLETED"
    assert completed.json()["data"]["available_actions"] == []

    again = await client.post(
        f"/api/v1/activities/{row['id']}/complete",
        headers=headers,
        json={},
    )
    assert again.status_code == 409, again.text
    assert again.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


@pytest.mark.asyncio
async def test_activity_rejects_unknown_related_type(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    response = await client.post(
        "/api/v1/activities",
        headers=headers,
        json={
            "activity_type": "CALL",
            "subject": "Bad related",
            "related_entity_type": "supplier",
            "related_entity_id": str(uuid4()),
        },
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_activity_overdue_filter(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    lead_id = await _create_lead(client, headers)
    past = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    created = await client.post(
        "/api/v1/activities",
        headers=headers,
        json={
            "activity_type": "TASK",
            "subject": "Overdue task",
            "related_entity_type": "lead",
            "related_entity_id": lead_id,
            "due_at": past,
        },
    )
    assert created.status_code == 201, created.text
    listed = await client.get("/api/v1/activities", headers=headers, params={"overdue": True})
    assert listed.status_code == 200, listed.text
    ids = {row["id"] for row in listed.json()["data"]}
    assert created.json()["data"]["id"] in ids

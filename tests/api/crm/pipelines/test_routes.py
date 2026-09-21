"""API tests for pipeline and stage CRUD."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_pipeline_seeded_with_default_stages(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    listed = await client.get("/api/v1/pipelines?is_default=true", headers=headers)
    assert listed.status_code == 200, listed.text
    rows = listed.json()["data"]
    assert len(rows) >= 1
    pipeline_id = rows[0]["id"]
    detail = await client.get(f"/api/v1/pipelines/{pipeline_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    stages = detail.json()["data"]["stages"]
    assert len(stages) == 6
    assert {stage["stage_kind"] for stage in stages} == {"OPEN", "WON", "LOST"}


@pytest.mark.asyncio
async def test_pipeline_stage_crud(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:6]
    created = await client.post(
        "/api/v1/pipelines",
        headers=headers,
        json={"name": f"Partner pipeline {suffix}"},
    )
    assert created.status_code == 201, created.text
    pipeline_id = created.json()["data"]["id"]
    stage = await client.post(
        f"/api/v1/pipelines/{pipeline_id}/stages",
        headers=headers,
        json={
            "name": "Discovery",
            "sort_order": 1,
            "probability": "15",
            "stage_kind": "OPEN",
        },
    )
    assert stage.status_code == 201, stage.text
    stage_id = stage.json()["data"]["id"]
    updated = await client.patch(
        f"/api/v1/pipelines/{pipeline_id}/stages/{stage_id}",
        headers=headers,
        json={"probability": "25"},
    )
    assert updated.status_code == 200, updated.text
    deleted = await client.delete(
        f"/api/v1/pipelines/{pipeline_id}/stages/{stage_id}",
        headers=headers,
    )
    assert deleted.status_code == 200, deleted.text


@pytest.mark.asyncio
async def test_default_pipeline_cannot_be_deleted(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    listed = await client.get("/api/v1/pipelines?is_default=true", headers=headers)
    pipeline_id = listed.json()["data"][0]["id"]
    deleted = await client.delete(f"/api/v1/pipelines/{pipeline_id}", headers=headers)
    assert deleted.status_code == 422, deleted.text
    assert deleted.json()["error"]["code"] == "VALIDATION_ERROR"

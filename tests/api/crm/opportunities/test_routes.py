"""API tests for opportunity CRUD and workflow."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _default_pipeline_stages(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[str, list[dict]]:
    pipelines = await client.get("/api/v1/pipelines", headers=headers)
    assert pipelines.status_code == 200, pipelines.text
    pipeline_id = pipelines.json()["data"][0]["id"]
    detail = await client.get(f"/api/v1/pipelines/{pipeline_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    return pipeline_id, detail.json()["data"]["stages"]


@pytest.mark.asyncio
async def test_opportunity_crud_stage_win_and_stale_version(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    pipeline_id, stages = await _default_pipeline_stages(client, headers)
    open_stage = next(stage for stage in stages if stage["stage_kind"] == "OPEN")

    created = await client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={
            "name": f"Enterprise {uuid4().hex[:6]}",
            "pipeline_id": pipeline_id,
            "stage_id": open_stage["id"],
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    assert row["opportunity_number"].startswith("OPP-")
    assert row["status"] == "OPEN"
    assert "win" in row["available_actions"]

    touched = await client.patch(
        f"/api/v1/opportunities/{row['id']}",
        headers={**headers, "If-Match": str(row["version"])},
        json={"name": row["name"]},
    )
    assert touched.status_code == 200, touched.text
    row = touched.json()["data"]

    stale = await client.patch(
        f"/api/v1/opportunities/{row['id']}",
        headers={**headers, "If-Match": "1"},
        json={"name": "Should fail"},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "DOCUMENT_STALE"

    won = await client.post(
        f"/api/v1/opportunities/{row['id']}/win",
        headers={**headers, "If-Match": str(row["version"])},
        json={},
    )
    assert won.status_code == 200, won.text
    assert won.json()["data"]["status"] == "WON"
    assert won.json()["data"]["available_actions"] == ["reopen"]


@pytest.mark.asyncio
async def test_lose_requires_lost_reason(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    pipeline_id, stages = await _default_pipeline_stages(client, headers)
    open_stage = next(stage for stage in stages if stage["stage_kind"] == "OPEN")
    lost_stage = next(stage for stage in stages if stage["stage_kind"] == "LOST")

    created = await client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={
            "name": f"Lost deal {uuid4().hex[:6]}",
            "pipeline_id": pipeline_id,
            "stage_id": open_stage["id"],
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]

    missing_reason = await client.post(
        f"/api/v1/opportunities/{row['id']}/stage",
        headers={**headers, "If-Match": str(row["version"])},
        json={"stage_id": lost_stage["id"]},
    )
    assert missing_reason.status_code == 422, missing_reason.text

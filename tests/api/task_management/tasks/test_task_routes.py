"""Task route smoke tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_task_crud_and_move(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    title = f"Task {uuid4().hex[:8]}"

    created = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": title, "priority": "HIGH"},
    )
    assert created.status_code == 201, created.text
    body = created.json()["data"]
    task_id = body["id"]
    assert body["status"] == "TODO"
    assert body["task_number"].startswith("TASK-")
    assert "move:IN_PROGRESS" in body["available_actions"]

    moved = await client.post(
        f"/api/v1/tasks/{task_id}/move",
        headers=headers,
        json={"status": "IN_PROGRESS", "sort_order": 0},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["data"]["status"] == "IN_PROGRESS"

    updated = await client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=headers,
        json={"title": f"{title} updated"},
    )
    assert updated.status_code == 200, updated.text

    deleted = await client.delete(f"/api/v1/tasks/{task_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text

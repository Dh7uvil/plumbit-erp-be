"""Forgot and reset password routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_forgot_and_reset_password(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    unknown = await client.post(
        "/api/v1/auth/forgot-password",
        json={"tenant_id": str(tenant_id), "email": "nobody@example.com"},
    )
    assert unknown.status_code == 200, unknown.text
    assert unknown.json()["data"]["reset_token"] is None

    requested = await client.post(
        "/api/v1/auth/forgot-password",
        json={"tenant_id": str(tenant_id), "email": email},
    )
    assert requested.status_code == 200, requested.text
    token = requested.json()["data"]["reset_token"]
    assert token

    bad = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": "not-a-real-token", "new_password": "NewPass123"},
    )
    assert bad.status_code == 401, bad.text

    reset = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "NewPass123"},
    )
    assert reset.status_code == 200, reset.text

    old = await client.post(
        "/api/v1/auth/login",
        json={"tenant_id": str(tenant_id), "email": email, "password": password},
    )
    assert old.status_code == 401, old.text

    headers = await login_headers(client, tenant_id, email, "NewPass123")
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    reused = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "AnotherPass1"},
    )
    assert reused.status_code == 401, reused.text

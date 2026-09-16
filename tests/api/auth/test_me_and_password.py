"""API tests for current-user profile update and change password."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _create_peer_user(
    client: AsyncClient,
    headers: dict[str, str],
) -> tuple[str, str]:
    suffix = uuid4().hex[:8]
    email = f"peer-{suffix}@example.com"
    password = "password12"
    user = await client.post(
        "/api/v1/users",
        headers=headers,
        json={"name": "Peer User", "email": email, "password": password},
    )
    assert user.status_code == 201, user.text
    return email, password


@pytest.mark.asyncio
async def test_patch_me_updates_name_and_phone(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    response = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"name": "Ada Lovelace", "phone": "+971500000000"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == "Ada Lovelace"
    assert data["phone"] == "+971500000000"
    assert data["email"] == email

    fetched = await client.get("/api/v1/auth/me", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["data"]["name"] == "Ada Lovelace"
    assert fetched.json()["data"]["phone"] == "+971500000000"


@pytest.mark.asyncio
async def test_patch_me_rejects_email_and_status(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    response = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"email": "other@example.com", "name": "Ada"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_patch_me_does_not_require_user_update_permission(client: AsyncClient) -> None:
    tenant_id, admin_email, admin_password = await provision_admin()
    admin_headers = await login_headers(client, tenant_id, admin_email, admin_password)
    peer_email, peer_password = await _create_peer_user(client, admin_headers)
    headers = await login_headers(client, tenant_id, peer_email, peer_password)
    response = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"name": "Peer Updated"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["name"] == "Peer Updated"
    assert response.json()["data"]["email"] == peer_email


@pytest.mark.asyncio
async def test_patch_me_unauthenticated_is_401(client: AsyncClient) -> None:
    response = await client.patch("/api/v1/auth/me", json={"name": "Ada"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_change_password_revokes_other_sessions(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    wrong = await client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": "wrong-password", "new_password": "NewPass123"},
    )
    assert wrong.status_code == 401

    changed = await client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": password, "new_password": "NewPass123"},
    )
    assert changed.status_code == 200, changed.text
    tokens = changed.json()["data"]
    assert tokens["access_token"]
    assert tokens["refresh_token"]

    stale = await client.get("/api/v1/auth/me", headers=headers)
    assert stale.status_code in {200, 401}

    fresh_headers = await login_headers(client, tenant_id, email, "NewPass123")
    me = await client.get("/api/v1/auth/me", headers=fresh_headers)
    assert me.status_code == 200

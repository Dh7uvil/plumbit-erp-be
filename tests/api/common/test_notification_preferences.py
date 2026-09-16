"""API tests for current-user notification preferences."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin

_PATH = "/api/v1/users/me/notification-preferences"


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
async def test_get_returns_defaults(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    response = await client.get(_PATH, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data == {
        "email_enabled": True,
        "in_app_enabled": True,
        "whatsapp_enabled": False,
        "is_default": True,
    }


@pytest.mark.asyncio
async def test_patch_persists_and_get_returns_saved(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    saved = await client.patch(
        _PATH,
        headers=headers,
        json={"email_enabled": False, "whatsapp_enabled": True},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()["data"]
    assert body == {
        "email_enabled": False,
        "in_app_enabled": True,
        "whatsapp_enabled": True,
        "is_default": False,
    }

    fetched = await client.get(_PATH, headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["data"] == body


@pytest.mark.asyncio
async def test_unauthenticated_is_401(client: AsyncClient) -> None:
    response = await client.get(_PATH)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_patch_unknown_field_is_422(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    response = await client.patch(_PATH, headers=headers, json={"sms_enabled": True})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_same_tenant_users_are_isolated(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers_a = await login_headers(client, tenant_id, email, password)
    peer_email, peer_password = await _create_peer_user(client, headers_a)
    headers_b = await login_headers(client, tenant_id, peer_email, peer_password)

    await client.patch(_PATH, headers=headers_a, json={"email_enabled": False})
    peer = await client.get(_PATH, headers=headers_b)
    assert peer.status_code == 200
    assert peer.json()["data"]["is_default"] is True
    assert peer.json()["data"]["email_enabled"] is True


@pytest.mark.asyncio
async def test_cross_tenant_preferences_are_isolated(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)

    await client.patch(_PATH, headers=headers_a, json={"in_app_enabled": False})
    other = await client.get(_PATH, headers=headers_b)
    assert other.status_code == 200
    assert other.json()["data"]["is_default"] is True
    assert other.json()["data"]["in_app_enabled"] is True

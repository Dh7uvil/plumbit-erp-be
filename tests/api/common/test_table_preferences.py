"""API tests for current-user table column preferences."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin

_TABLE = "erp.exchange_rates"
_PATH = f"/api/v1/users/me/table-preferences/{_TABLE}"


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
async def test_get_returns_catalog_defaults(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    response = await client.get(_PATH, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["table_key"] == _TABLE
    assert data["is_default"] is True
    assert data["visible_columns"] == ["from_currency", "to_currency", "rate", "effective_date"]
    assert data["column_order"][:4] == ["from_currency", "to_currency", "rate", "effective_date"]
    assert "created_at" in data["column_order"]


@pytest.mark.asyncio
async def test_put_persists_and_get_returns_saved(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    payload = {
        "visible_columns": ["rate", "effective_date"],
        "column_order": ["effective_date", "rate", "from_currency"],
    }
    saved = await client.put(_PATH, headers=headers, json=payload)
    assert saved.status_code == 200, saved.text
    body = saved.json()["data"]
    assert body["is_default"] is False
    assert body["visible_columns"][:2] == ["from_currency", "to_currency"]
    assert body["visible_columns"][2:] == ["rate", "effective_date"]
    assert body["column_order"][:2] == ["from_currency", "to_currency"]
    assert "effective_date" in body["column_order"]
    assert "rate" in body["column_order"]

    fetched = await client.get(_PATH, headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["data"] == body


@pytest.mark.asyncio
async def test_delete_resets_to_default(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await client.put(
        _PATH,
        headers=headers,
        json={"visible_columns": ["rate"], "column_order": ["rate"]},
    )
    reset = await client.delete(_PATH, headers=headers)
    assert reset.status_code == 200, reset.text
    data = reset.json()["data"]
    assert data["is_default"] is True
    assert data["visible_columns"] == ["from_currency", "to_currency", "rate", "effective_date"]

    again = await client.delete(_PATH, headers=headers)
    assert again.status_code == 200
    assert again.json()["data"]["is_default"] is True


@pytest.mark.asyncio
async def test_unknown_table_key_not_found(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    response = await client.get(
        "/api/v1/users/me/table-preferences/erp.unknown_table",
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_unauthenticated_is_401(client: AsyncClient) -> None:
    response = await client.get(_PATH)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_put_illegal_column_is_422(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    response = await client.put(
        _PATH,
        headers=headers,
        json={"visible_columns": ["rate", "secret"], "column_order": ["rate"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_put_empty_visible_is_422(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    response = await client.put(
        _PATH,
        headers=headers,
        json={"visible_columns": [], "column_order": ["rate"]},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_same_tenant_users_are_isolated(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers_a = await login_headers(client, tenant_id, email, password)
    peer_email, peer_password = await _create_peer_user(client, headers_a)
    headers_b = await login_headers(client, tenant_id, peer_email, peer_password)

    await client.put(
        _PATH,
        headers=headers_a,
        json={"visible_columns": ["rate"], "column_order": ["rate"]},
    )
    peer = await client.get(_PATH, headers=headers_b)
    assert peer.status_code == 200
    assert peer.json()["data"]["is_default"] is True
    assert peer.json()["data"]["visible_columns"] == [
        "from_currency",
        "to_currency",
        "rate",
        "effective_date",
    ]


@pytest.mark.asyncio
async def test_cross_tenant_preferences_are_isolated(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)

    await client.put(
        _PATH,
        headers=headers_a,
        json={
            "visible_columns": ["effective_date"],
            "column_order": ["effective_date", "rate", "from_currency"],
        },
    )
    other = await client.get(_PATH, headers=headers_b)
    assert other.status_code == 200
    assert other.json()["data"]["is_default"] is True

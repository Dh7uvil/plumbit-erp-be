"""Privilege-escalation and last-Superadmin guards."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _permission_id(client: AsyncClient, headers: dict[str, str], code: str) -> str:
    page = 1
    while True:
        permissions = await client.get(
            f"/api/v1/permissions?page={page}&page_size=100",
            headers=headers,
        )
        assert permissions.status_code == 200, permissions.text
        payload = permissions.json()
        match = next((item for item in payload["data"] if item["code"] == code), None)
        if match is not None:
            return match["id"]
        total = payload["meta"]["total"]
        if page * 100 >= total:
            raise AssertionError(f"Permission {code} not found")
        page += 1


async def _create_user_with_permissions(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    permission_codes: list[str],
) -> tuple[str, str, str]:
    permission_ids = [
        await _permission_id(client, headers, code) for code in permission_codes
    ]
    suffix = uuid4().hex[:8]
    email = f"limited-{suffix}@example.com"
    password = "password12"
    role = await client.post(
        "/api/v1/roles",
        headers=headers,
        json={"name": f"Limited {suffix}", "permission_ids": permission_ids},
    )
    assert role.status_code == 201, role.text
    user = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "Limited User",
            "email": email,
            "password": password,
            "role_ids": [role.json()["data"]["id"]],
        },
    )
    assert user.status_code == 201, user.text
    return user.json()["data"]["id"], email, password


async def _superadmin_role_id(client: AsyncClient, headers: dict[str, str]) -> str:
    roles = await client.get("/api/v1/roles", headers=headers)
    assert roles.status_code == 200, roles.text
    return next(item["id"] for item in roles.json()["data"] if item["name"] == "Superadmin")


@pytest.mark.asyncio
async def test_user_cannot_change_own_roles(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    user_id = me.json()["data"]["id"]
    superadmin_id = await _superadmin_role_id(client, headers)
    assigned = await client.put(
        f"/api/v1/users/{user_id}/roles",
        headers=headers,
        json={"role_ids": [superadmin_id]},
    )
    assert assigned.status_code == 422, assigned.text
    assert assigned.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "own role" in assigned.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_non_superadmin_cannot_assign_superadmin(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    _, limited_email, limited_password = await _create_user_with_permissions(
        client,
        headers,
        permission_codes=["identity.user.update", "identity.user.read", "identity.role.read"],
    )
    target = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "Target User",
            "email": f"target-{uuid4().hex[:8]}@example.com",
            "password": "password12",
            "role_ids": [],
        },
    )
    assert target.status_code == 201, target.text
    limited_headers = await login_headers(client, tenant_id, limited_email, limited_password)
    superadmin_id = await _superadmin_role_id(client, headers)
    assigned = await client.put(
        f"/api/v1/users/{target.json()['data']['id']}/roles",
        headers=limited_headers,
        json={"role_ids": [superadmin_id]},
    )
    assert assigned.status_code == 422, assigned.text
    assert "superadmin" in assigned.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_cannot_strip_last_active_superadmin_roles(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    me = await client.get("/api/v1/auth/me", headers=headers)
    admin_id = me.json()["data"]["id"]
    _, limited_email, limited_password = await _create_user_with_permissions(
        client,
        headers,
        permission_codes=["identity.user.update", "identity.user.read"],
    )
    limited_headers = await login_headers(client, tenant_id, limited_email, limited_password)
    stripped = await client.put(
        f"/api/v1/users/{admin_id}/roles",
        headers=limited_headers,
        json={"role_ids": []},
    )
    assert stripped.status_code == 422, stripped.text
    assert "last active superadmin" in stripped.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_cannot_deactivate_last_active_superadmin(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    me = await client.get("/api/v1/auth/me", headers=headers)
    admin_id = me.json()["data"]["id"]
    _, limited_email, limited_password = await _create_user_with_permissions(
        client,
        headers,
        permission_codes=["identity.user.delete", "identity.user.read", "identity.user.update"],
    )
    limited_headers = await login_headers(client, tenant_id, limited_email, limited_password)
    last = await client.post(f"/api/v1/users/{admin_id}/deactivate", headers=limited_headers)
    assert last.status_code == 422, last.text
    assert "last active superadmin" in last.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_cannot_delete_role_assigned_to_users(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    role = await client.post(
        "/api/v1/roles",
        headers=headers,
        json={"name": f"Assigned {uuid4().hex[:6]}", "permission_ids": []},
    )
    assert role.status_code == 201, role.text
    role_id = role.json()["data"]["id"]
    user = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "Role User",
            "email": f"role-user-{uuid4().hex[:8]}@example.com",
            "password": "password12",
            "role_ids": [role_id],
        },
    )
    assert user.status_code == 201, user.text
    deleted = await client.delete(f"/api/v1/roles/{role_id}", headers=headers)
    assert deleted.status_code == 422, deleted.text
    assert "assigned to users" in deleted.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_superadmin_permissions_cannot_be_edited_manually(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    superadmin_id = await _superadmin_role_id(client, headers)
    updated = await client.put(
        f"/api/v1/roles/{superadmin_id}/permissions",
        headers=headers,
        json={"permission_ids": []},
    )
    assert updated.status_code == 422, updated.text
    assert "cannot be edited manually" in updated.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_non_superadmin_cannot_reset_superadmin_permissions(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    _, limited_email, limited_password = await _create_user_with_permissions(
        client,
        headers,
        permission_codes=["identity.role.update", "identity.role.read"],
    )
    limited_headers = await login_headers(client, tenant_id, limited_email, limited_password)
    superadmin_id = await _superadmin_role_id(client, headers)
    reset = await client.post(
        f"/api/v1/roles/{superadmin_id}/permissions/reset",
        headers=limited_headers,
    )
    assert reset.status_code == 422, reset.text
    assert "only a superadmin" in reset.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_admin_reset_user_password_and_rejects_self(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    me = await client.get("/api/v1/auth/me", headers=headers)
    self_reset = await client.post(
        f"/api/v1/users/{me.json()['data']['id']}/password-reset",
        headers=headers,
        json={"new_password": "NewPass123"},
    )
    assert self_reset.status_code == 422, self_reset.text
    created = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "Reset Target",
            "email": f"reset-{uuid4().hex[:8]}@example.com",
            "password": "password12",
            "role_ids": [],
        },
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["data"]["id"]
    target_email = created.json()["data"]["email"]
    reset = await client.post(
        f"/api/v1/users/{user_id}/password-reset",
        headers=headers,
        json={"new_password": "NewPass123"},
    )
    assert reset.status_code == 200, reset.text
    old = await client.post(
        "/api/v1/auth/login",
        json={"tenant_id": tenant_id, "email": target_email, "password": "password12"},
    )
    assert old.status_code == 401, old.text
    new_login = await client.post(
        "/api/v1/auth/login",
        json={"tenant_id": tenant_id, "email": target_email, "password": "NewPass123"},
    )
    assert new_login.status_code == 200, new_login.text


@pytest.mark.asyncio
async def test_new_tenant_timezone_defaults_to_dubai(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    current = await client.get("/api/v1/tenants/current", headers=headers)
    assert current.status_code == 200, current.text
    assert current.json()["data"]["timezone"] == "Asia/Dubai"


@pytest.mark.asyncio
async def test_audit_logs_export_csv(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    exported = await client.get("/api/v1/audit-logs/export.csv", headers=headers)
    assert exported.status_code == 200, exported.text
    assert "text/csv" in exported.headers.get("content-type", "")
    assert b"action" in exported.content.lower()

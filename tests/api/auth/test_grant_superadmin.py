"""API tests for granting the catalog to Superadmin via CLI."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.auth.catalog import CATALOG_PERMISSIONS, SYSTEM_ADMIN_ROLE_NAME
from app.auth.models import Permission, Role, RolePermission
from app.cli.grant_superadmin_permissions import grant_superadmin_permissions
from app.db.session import async_session_factory, transaction
from tests.conftest import login_headers, provision_admin


async def _superadmin_role_id(client: AsyncClient, headers: dict[str, str]) -> str:
    roles = await client.get("/api/v1/roles", headers=headers)
    assert roles.status_code == 200, roles.text
    admin = next(item for item in roles.json()["data"] if item["is_system_role"])
    assert admin["name"] == SYSTEM_ADMIN_ROLE_NAME
    return admin["id"]


async def _role_permission_codes(
    client: AsyncClient, headers: dict[str, str], role_id: str
) -> set[str]:
    detail = await client.get(f"/api/v1/roles/{role_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    return {item["code"] for item in detail.json()["data"]["permissions"]}


@pytest.mark.asyncio
async def test_grant_superadmin_permissions_restores_missing_catalog_grant(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    role_id = await _superadmin_role_id(client, headers)

    async with async_session_factory() as session, transaction(session):
        permission = await session.scalar(
            select(Permission).where(
                Permission.tenant_id == UUID(tenant_id),
                Permission.module == "erp",
                Permission.resource == "proforma_invoice",
                Permission.action == "create",
            )
        )
        assert permission is not None
        await session.execute(
            delete(RolePermission).where(
                RolePermission.tenant_id == UUID(tenant_id),
                RolePermission.permission_id == permission.id,
            )
        )

    assert "erp.proforma_invoice.create" not in await _role_permission_codes(
        client, headers, role_id
    )

    results = await grant_superadmin_permissions(tenant_id=UUID(tenant_id))
    assert len(results) == 1
    assert results[0].skipped is False
    assert results[0].catalog_permissions == len(CATALOG_PERMISSIONS)
    assert results[0].superadmin_users == 1

    codes = await _role_permission_codes(client, headers, role_id)
    assert codes == set(CATALOG_PERMISSIONS)


@pytest.mark.asyncio
async def test_grant_superadmin_permissions_seeds_missing_catalog_row(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    role_id = await _superadmin_role_id(client, headers)

    async with async_session_factory() as session, transaction(session):
        permission = await session.scalar(
            select(Permission).where(
                Permission.tenant_id == UUID(tenant_id),
                Permission.module == "erp",
                Permission.resource == "quotation",
                Permission.action == "revise",
            )
        )
        assert permission is not None
        await session.execute(
            delete(RolePermission).where(
                RolePermission.tenant_id == UUID(tenant_id),
                RolePermission.permission_id == permission.id,
            )
        )
        await session.execute(delete(Permission).where(Permission.id == permission.id))

    results = await grant_superadmin_permissions(tenant_id=UUID(tenant_id))
    assert len(results) == 1
    assert results[0].skipped is False

    codes = await _role_permission_codes(client, headers, role_id)
    assert "erp.quotation.revise" in codes
    assert codes == set(CATALOG_PERMISSIONS)


@pytest.mark.asyncio
async def test_grant_superadmin_permissions_is_idempotent(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    role_id = await _superadmin_role_id(client, headers)

    first = await grant_superadmin_permissions(tenant_id=UUID(tenant_id))
    second = await grant_superadmin_permissions(tenant_id=UUID(tenant_id))
    assert first == second
    assert first[0].catalog_permissions == len(CATALOG_PERMISSIONS)
    assert await _role_permission_codes(client, headers, role_id) == set(CATALOG_PERMISSIONS)


@pytest.mark.asyncio
async def test_grant_superadmin_permissions_skips_tenant_without_superadmin_role() -> None:
    tenant_id, _, _ = await provision_admin()

    async with async_session_factory() as session, transaction(session):
        role = await session.scalar(
            select(Role).where(
                Role.tenant_id == UUID(tenant_id),
                Role.name == SYSTEM_ADMIN_ROLE_NAME,
                Role.is_system_role.is_(True),
            )
        )
        assert role is not None
        role.is_system_role = False

    results = await grant_superadmin_permissions(tenant_id=UUID(tenant_id))
    assert len(results) == 1
    assert results[0].skipped is True
    assert results[0].catalog_permissions == 0
    assert results[0].superadmin_users == 0


@pytest.mark.asyncio
async def test_grant_superadmin_permissions_rejects_unknown_tenant() -> None:
    with pytest.raises(ValueError, match="No active tenant matched"):
        await grant_superadmin_permissions(tenant_id=uuid4())

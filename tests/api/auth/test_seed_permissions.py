"""API tests for seeding missing permission catalog rows via CLI."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.auth.catalog import CATALOG_PERMISSIONS, SYSTEM_ADMIN_ROLE_NAME
from app.auth.models import Permission, RolePermission
from app.cli.seed_permissions import seed_catalog_permissions
from app.db.session import async_session_factory, transaction
from tests.conftest import login_headers, provision_admin


def _permission_code(row: Permission) -> str:
    return f"{row.module}.{row.resource}.{row.action}"


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
async def test_seed_catalog_permissions_inserts_missing_row(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    role_id = await _superadmin_role_id(client, headers)

    async with async_session_factory() as session, transaction(session):
        permission = await session.scalar(
            select(Permission).where(
                Permission.tenant_id == UUID(tenant_id),
                Permission.module == "inventory",
                Permission.resource == "goods_receipt",
                Permission.action == "post",
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

    results = await seed_catalog_permissions(tenant_id=UUID(tenant_id))
    assert len(results) == 1
    assert results[0].inserted == 1
    assert results[0].catalog_permissions == len(CATALOG_PERMISSIONS)

    async with async_session_factory() as session:
        restored = await session.scalar(
            select(Permission).where(
                Permission.tenant_id == UUID(tenant_id),
                Permission.module == "inventory",
                Permission.resource == "goods_receipt",
                Permission.action == "post",
            )
        )
        assert restored is not None
        codes = {
            _permission_code(row)
            for row in (
                await session.scalars(
                    select(Permission).where(Permission.tenant_id == UUID(tenant_id))
                )
            ).all()
        }
    assert "purchase.goods_receipt.post" in codes
    assert set(CATALOG_PERMISSIONS).issubset(codes)
    assert "purchase.goods_receipt.post" not in await _role_permission_codes(
        client, headers, role_id
    )


@pytest.mark.asyncio
async def test_seed_catalog_permissions_is_idempotent(client: AsyncClient) -> None:
    tenant_id, _, _ = await provision_admin()

    first = await seed_catalog_permissions(tenant_id=UUID(tenant_id))
    second = await seed_catalog_permissions(tenant_id=UUID(tenant_id))
    assert first[0].inserted == 0
    assert second[0].inserted == 0
    assert first[0].catalog_permissions == len(CATALOG_PERMISSIONS)
    assert first == second


@pytest.mark.asyncio
async def test_seed_catalog_permissions_rejects_unknown_tenant() -> None:
    with pytest.raises(ValueError, match="No active tenant matched"):
        await seed_catalog_permissions(tenant_id=uuid4())

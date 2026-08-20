"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.cli.create_tenant import provision_tenant
from app.core.security import hash_password
from app.main import create_app

ADMIN_PASSWORD = "password12"


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as http:
        yield http


async def provision_admin(*, name: str | None = None) -> tuple[str, str, str]:
    suffix = uuid4().hex[:8]
    tenant_name = name or f"Test Tenant {suffix}"
    admin_email = f"admin-{suffix}@example.com"
    result = await provision_tenant(
        tenant_name=tenant_name,
        admin_name="Admin User",
        admin_email=admin_email,
        password_hash=hash_password(ADMIN_PASSWORD),
    )
    return str(result.tenant_id), admin_email, ADMIN_PASSWORD


async def login_headers(
    client: AsyncClient,
    tenant_id: str,
    email: str,
    password: str = ADMIN_PASSWORD,
) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"tenant_id": tenant_id, "email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}

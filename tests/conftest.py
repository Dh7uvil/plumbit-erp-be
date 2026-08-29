"""Shared pytest fixtures.

Loads `.env.test` before any application import so tests cannot connect to the
development database. The process then fails fast unless `DATABASE_NAME` is
exactly `plumb_it_test`.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

_TEST_ENV_PATH = Path(__file__).resolve().parents[1] / ".env.test"
if not _TEST_ENV_PATH.is_file():
    raise RuntimeError(
        f"pytest requires {_TEST_ENV_PATH}. Copy .env.test.example to .env.test "
        "and set DATABASE_NAME=plumb_it_test."
    )
if not load_dotenv(_TEST_ENV_PATH, override=True):
    raise RuntimeError(f"Failed to load pytest environment file {_TEST_ENV_PATH}")

from collections.abc import AsyncIterator  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.cli.create_tenant import provision_tenant  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import create_app  # noqa: E402

get_settings.cache_clear()
_SETTINGS = get_settings()
if _SETTINGS.env != "testing":
    raise RuntimeError("pytest requires ENV=testing in .env.test")
if _SETTINGS.database_name != "plumb_it_test":
    raise RuntimeError(
        f"pytest refuses to run against database {_SETTINGS.database_name!r}; "
        "set DATABASE_NAME=plumb_it_test in .env.test"
    )

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

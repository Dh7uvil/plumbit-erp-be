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

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()
_SETTINGS = get_settings()
if _SETTINGS.env != "testing":
    raise RuntimeError("pytest requires ENV=testing in .env.test")
if _SETTINGS.database_name != "plumb_it_test":
    raise RuntimeError(
        f"pytest refuses to run against database {_SETTINGS.database_name!r}; "
        "set DATABASE_NAME=plumb_it_test in .env.test"
    )

ADMIN_PASSWORD = "Password12"


@pytest.fixture(scope="session", autouse=True)
def ensure_test_db_migrated() -> None:
    """Apply Alembic migrations to the test database before any tests run."""

    from alembic import command
    from alembic.config import Config
    from alembic.util.exc import CommandError

    alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        command.upgrade(alembic_cfg, "head")
    except CommandError as exc:
        message = str(exc)
        if "Can't locate revision" not in message:
            raise
        # Orphan alembic_version: stamp to last known good revision, then upgrade.
        command.stamp(alembic_cfg, "q2r3s4t5u678")
        command.upgrade(alembic_cfg, "head")
        return

    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _accounts_missing_default_tax_id() -> bool:
        engine = create_async_engine(str(_SETTINGS.database_url))
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'accounts' "
                        "AND column_name = 'default_tax_id'"
                    )
                )
                return result.scalar() is None
        finally:
            await engine.dispose()

    if asyncio.run(_accounts_missing_default_tax_id()):
        command.stamp(alembic_cfg, "q2r3s4t5u678")
        command.upgrade(alembic_cfg, "head")


def unique_trn(*, prefix: str = "1") -> str:
    """Return a 15-digit TRN unlikely to collide within a tenant."""

    return f"{prefix}{uuid4().int % 10**14:014d}"[:15]


@pytest.fixture
def app():
    from app.main import create_app

    return create_app()


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as http:
        yield http


async def provision_admin(*, name: str | None = None) -> tuple[str, str, str]:
    from app.cli.create_tenant import provision_tenant
    from app.core.security import hash_password

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

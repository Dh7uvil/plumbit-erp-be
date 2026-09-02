"""Seeds that run as part of tenant provisioning.

Called after the tenant, admin role, and admin user exist. Currencies are loaded
first so the tenant default can point at AED, then operational masters.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.seeds.common import seed_common_data
from app.db.seeds.required import seed_required_masters


async def seed_on_tenant_create(session: AsyncSession, tenant_id: UUID) -> None:
    """Insert catalog currencies and required masters for a new tenant."""

    await seed_common_data(session, tenant_id)
    await seed_required_masters(session, tenant_id)

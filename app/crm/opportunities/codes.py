"""Allocate tenant-unique OPP-##### numbers."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Tenant
from app.crm.opportunities.models import OpportunityNumberCounter

_OPP_PREFIX = "OPP"
_PADDING = 5


def format_opportunity_number(sequence: int) -> str:
    """Return the display number for ``sequence`` (e.g. OPP-00001)."""

    return f"{_OPP_PREFIX}-{sequence:0{_PADDING}d}"


async def allocate_opportunity_number(session: AsyncSession, tenant_id: UUID) -> str:
    """Lock the tenant row and return the next opportunity number."""

    await session.execute(
        select(Tenant.id).where(Tenant.id == tenant_id).with_for_update()
    )
    statement = select(OpportunityNumberCounter).where(
        OpportunityNumberCounter.tenant_id == tenant_id
    )
    result = await session.execute(statement)
    counter = result.scalar_one_or_none()
    if counter is None:
        counter = OpportunityNumberCounter(tenant_id=tenant_id, next_number=1)
        session.add(counter)
        await session.flush()
    number = counter.next_number
    counter.next_number = number + 1
    await session.flush()
    return format_opportunity_number(number)

"""Allocate tenant-unique TASK-##### numbers."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Tenant
from app.task_management.tasks.models import TaskNumberCounter

_TASK_PREFIX = "TASK"
_PADDING = 5


def format_task_number(sequence: int) -> str:
    return f"{_TASK_PREFIX}-{sequence:0{_PADDING}d}"


async def allocate_task_number(session: AsyncSession, tenant_id: UUID) -> str:
    await session.execute(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update())
    statement = select(TaskNumberCounter).where(TaskNumberCounter.tenant_id == tenant_id)
    result = await session.execute(statement)
    counter = result.scalar_one_or_none()
    if counter is None:
        counter = TaskNumberCounter(tenant_id=tenant_id, next_number=1)
        session.add(counter)
        await session.flush()
    number = counter.next_number
    counter.next_number = number + 1
    await session.flush()
    return format_task_number(number)

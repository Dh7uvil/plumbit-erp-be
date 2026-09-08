"""Period-lock slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.erp.period_lock.service import PeriodLockService


def get_period_lock_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PeriodLockService:
    return PeriodLockService(session)


PeriodLockServiceDependency = Annotated[PeriodLockService, Depends(get_period_lock_service)]

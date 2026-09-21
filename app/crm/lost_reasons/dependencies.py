"""Lost reason slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.crm.lost_reasons.service import LostReasonService
from app.db.session import get_db


def get_lost_reason_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> LostReasonService:
    return LostReasonService(session)


LostReasonServiceDependency = Annotated[LostReasonService, Depends(get_lost_reason_service)]

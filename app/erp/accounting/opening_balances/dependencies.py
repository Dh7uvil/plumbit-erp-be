"""Opening-balance slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.accounting.opening_balances.service import OpeningBalanceService


def get_opening_balance_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> OpeningBalanceService:
    return OpeningBalanceService(session, actor_permissions=current_user.permissions)


OpeningBalanceServiceDependency = Annotated[
    OpeningBalanceService, Depends(get_opening_balance_service)
]

"""Credit-control slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.credit_control.service import CreditControlService


def get_credit_control_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> CreditControlService:
    return CreditControlService(session, actor_permissions=current_user.permissions)


CreditControlServiceDependency = Annotated[
    CreditControlService, Depends(get_credit_control_service)
]

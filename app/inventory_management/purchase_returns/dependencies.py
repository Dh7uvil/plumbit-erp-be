"""Purchase return slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.inventory_management.purchase_returns.service import PurchaseReturnService


def get_purchase_return_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> PurchaseReturnService:
    return PurchaseReturnService(session, actor_permissions=current_user.permissions)


PurchaseReturnServiceDependency = Annotated[PurchaseReturnService, Depends(get_purchase_return_service)]

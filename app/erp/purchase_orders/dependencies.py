"""Purchase order slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.purchase_orders.service import PurchaseOrderService


def get_purchase_order_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> PurchaseOrderService:
    return PurchaseOrderService(session, actor_permissions=current_user.permissions)


PurchaseOrderServiceDependency = Annotated[
    PurchaseOrderService, Depends(get_purchase_order_service)
]

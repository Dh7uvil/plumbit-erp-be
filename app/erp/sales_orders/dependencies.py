"""Sales order slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.sales_orders.service import SalesOrderService


def get_sales_order_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> SalesOrderService:
    return SalesOrderService(session, actor_permissions=current_user.permissions)


SalesOrderServiceDependency = Annotated[SalesOrderService, Depends(get_sales_order_service)]

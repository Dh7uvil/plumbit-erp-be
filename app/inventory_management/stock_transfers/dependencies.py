"""Stock transfer slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.inventory_management.stock_transfers.service import StockTransferService


def get_stock_transfer_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> StockTransferService:
    return StockTransferService(session, actor_permissions=current_user.permissions)


StockTransferServiceDependency = Annotated[
    StockTransferService, Depends(get_stock_transfer_service)
]

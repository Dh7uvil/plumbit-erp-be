"""Stock inquiry slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.inventory_management.stock.service import StockService


def get_stock_service(session: Annotated[AsyncSession, Depends(get_db)]) -> StockService:
    return StockService(session)


StockServiceDependency = Annotated[StockService, Depends(get_stock_service)]

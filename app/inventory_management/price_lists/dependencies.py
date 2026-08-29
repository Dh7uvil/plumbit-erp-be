"""Price-list slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.inventory_management.price_lists.service import PriceListService


def get_price_list_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PriceListService:
    return PriceListService(session)


PriceListServiceDependency = Annotated[PriceListService, Depends(get_price_list_service)]

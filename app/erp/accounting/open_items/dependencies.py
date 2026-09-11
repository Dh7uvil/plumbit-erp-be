"""Open-items slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.erp.accounting.open_items.service import OpenItemsService


def get_open_items_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> OpenItemsService:
    return OpenItemsService(session)


OpenItemsServiceDependency = Annotated[OpenItemsService, Depends(get_open_items_service)]

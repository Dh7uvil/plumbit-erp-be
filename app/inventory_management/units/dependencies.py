"""Unit slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.inventory_management.units.service import UnitService


def get_unit_service(session: Annotated[AsyncSession, Depends(get_db)]) -> UnitService:
    return UnitService(session)


UnitServiceDependency = Annotated[UnitService, Depends(get_unit_service)]

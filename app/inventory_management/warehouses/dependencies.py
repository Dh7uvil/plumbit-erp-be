"""Warehouse slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.inventory_management.warehouses.service import WarehouseService


def get_warehouse_service(session: Annotated[AsyncSession, Depends(get_db)]) -> WarehouseService:
    return WarehouseService(session)


WarehouseServiceDependency = Annotated[WarehouseService, Depends(get_warehouse_service)]

"""Cost center slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.erp.accounting.cost_centers.service import CostCenterService


def get_cost_center_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CostCenterService:
    return CostCenterService(session)


CostCenterServiceDependency = Annotated[CostCenterService, Depends(get_cost_center_service)]

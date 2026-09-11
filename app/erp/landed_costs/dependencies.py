"""Landed cost slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.landed_costs.service import LandedCostService


def get_landed_cost_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> LandedCostService:
    return LandedCostService(session, actor_permissions=current_user.permissions)


LandedCostServiceDependency = Annotated[LandedCostService, Depends(get_landed_cost_service)]

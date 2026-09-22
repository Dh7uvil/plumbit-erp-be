"""Cost sheet slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.cost_sheets.service import CostSheetService


def get_cost_sheet_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> CostSheetService:
    return CostSheetService(session, actor_permissions=current_user.permissions)


CostSheetServiceDependency = Annotated[CostSheetService, Depends(get_cost_sheet_service)]

"""Quality inspection slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.inventory_management.quality_inspections.service import QualityInspectionService


def get_quality_inspection_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> QualityInspectionService:
    return QualityInspectionService(session, actor_permissions=current_user.permissions)


QualityInspectionServiceDependency = Annotated[
    QualityInspectionService, Depends(get_quality_inspection_service)
]

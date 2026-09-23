"""FX revaluation slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.accounting.fx_revaluation.service import FxRevaluationService


def get_fx_revaluation_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> FxRevaluationService:
    return FxRevaluationService(session, actor_permissions=current_user.permissions)


FxRevaluationServiceDependency = Annotated[
    FxRevaluationService, Depends(get_fx_revaluation_service)
]

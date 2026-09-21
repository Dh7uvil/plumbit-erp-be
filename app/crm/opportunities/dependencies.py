"""Opportunity slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.crm.opportunities.service import OpportunityService
from app.db.session import get_db


def get_opportunity_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> OpportunityService:
    return OpportunityService(session, actor_permissions=current_user.permissions)


OpportunityServiceDependency = Annotated[OpportunityService, Depends(get_opportunity_service)]

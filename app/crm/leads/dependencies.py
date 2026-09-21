"""Lead slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.crm.leads.service import LeadService
from app.db.session import get_db


def get_lead_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> LeadService:
    return LeadService(session, actor_permissions=current_user.permissions)


LeadServiceDependency = Annotated[LeadService, Depends(get_lead_service)]

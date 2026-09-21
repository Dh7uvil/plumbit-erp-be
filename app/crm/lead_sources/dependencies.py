"""Lead source slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.crm.lead_sources.service import LeadSourceService
from app.db.session import get_db


def get_lead_source_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> LeadSourceService:
    return LeadSourceService(session)


LeadSourceServiceDependency = Annotated[LeadSourceService, Depends(get_lead_source_service)]

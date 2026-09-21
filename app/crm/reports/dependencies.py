"""CRM report slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.crm.reports.service import CrmReportService
from app.db.session import get_db


def get_crm_report_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CrmReportService:
    return CrmReportService(session)


CrmReportServiceDependency = Annotated[CrmReportService, Depends(get_crm_report_service)]

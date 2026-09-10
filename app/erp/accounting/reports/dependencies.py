"""Ledger report slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.erp.accounting.reports.service import ReportService


def get_report_service(session: Annotated[AsyncSession, Depends(get_db)]) -> ReportService:
    return ReportService(session)


ReportServiceDependency = Annotated[ReportService, Depends(get_report_service)]

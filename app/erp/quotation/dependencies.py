"""Quotation slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.erp.quotation.service import QuotationService


def get_quotation_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> QuotationService:
    return QuotationService(session)


QuotationServiceDependency = Annotated[QuotationService, Depends(get_quotation_service)]

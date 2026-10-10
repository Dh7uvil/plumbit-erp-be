"""Financial category dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.erp.accounting.financial_categories.service import FinancialCategoryService


def get_financial_category_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> FinancialCategoryService:
    return FinancialCategoryService(session)


FinancialCategoryServiceDependency = Annotated[
    FinancialCategoryService, Depends(get_financial_category_service)
]

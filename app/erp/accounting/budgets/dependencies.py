"""Budget slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.erp.accounting.budgets.service import BudgetService


def get_budget_service(session: Annotated[AsyncSession, Depends(get_db)]) -> BudgetService:
    return BudgetService(session)


BudgetServiceDependency = Annotated[BudgetService, Depends(get_budget_service)]

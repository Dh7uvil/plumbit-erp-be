"""Bank reconciliation slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.erp.accounting.bank_reconciliation.service import BankReconciliationService


def get_bank_reconciliation_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BankReconciliationService:
    return BankReconciliationService(session)


BankReconciliationServiceDependency = Annotated[
    BankReconciliationService, Depends(get_bank_reconciliation_service)
]

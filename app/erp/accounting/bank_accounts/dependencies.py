"""Bank account slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.erp.accounting.bank_accounts.service import BankAccountService


def get_bank_account_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BankAccountService:
    return BankAccountService(session)


BankAccountServiceDependency = Annotated[BankAccountService, Depends(get_bank_account_service)]

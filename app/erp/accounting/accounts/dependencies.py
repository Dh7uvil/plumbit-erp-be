"""Chart of accounts slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.erp.accounting.accounts.service import AccountService


def get_account_service(session: Annotated[AsyncSession, Depends(get_db)]) -> AccountService:
    return AccountService(session)


AccountServiceDependency = Annotated[AccountService, Depends(get_account_service)]

"""Customer slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.crm.customers.party_balances import PartyBalanceService
from app.crm.customers.service import CustomerService
from app.db.session import get_db


def get_customer_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CustomerService:
    return CustomerService(session)


def get_party_balance_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PartyBalanceService:
    return PartyBalanceService(session)


CustomerServiceDependency = Annotated[CustomerService, Depends(get_customer_service)]
PartyBalanceServiceDependency = Annotated[PartyBalanceService, Depends(get_party_balance_service)]

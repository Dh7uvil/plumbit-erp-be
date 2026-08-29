"""Customer slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.crm.customers.service import CustomerService
from app.db.session import get_db


def get_customer_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CustomerService:
    return CustomerService(session)


CustomerServiceDependency = Annotated[CustomerService, Depends(get_customer_service)]

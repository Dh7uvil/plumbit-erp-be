"""Customer payment slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.customer_payments.service import CustomerPaymentService


def get_customer_payment_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> CustomerPaymentService:
    return CustomerPaymentService(session, actor_permissions=current_user.permissions)


CustomerPaymentServiceDependency = Annotated[
    CustomerPaymentService, Depends(get_customer_payment_service)
]

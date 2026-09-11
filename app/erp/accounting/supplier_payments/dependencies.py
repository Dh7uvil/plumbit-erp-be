"""Supplier payment slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.accounting.supplier_payments.service import SupplierPaymentService


def get_supplier_payment_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> SupplierPaymentService:
    return SupplierPaymentService(session, actor_permissions=current_user.permissions)


SupplierPaymentServiceDependency = Annotated[
    SupplierPaymentService, Depends(get_supplier_payment_service)
]

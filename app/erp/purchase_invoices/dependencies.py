"""Purchase invoice slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.purchase_invoices.service import PurchaseInvoiceService


def get_purchase_invoice_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> PurchaseInvoiceService:
    return PurchaseInvoiceService(session, actor_permissions=current_user.permissions)


PurchaseInvoiceServiceDependency = Annotated[
    PurchaseInvoiceService, Depends(get_purchase_invoice_service)
]

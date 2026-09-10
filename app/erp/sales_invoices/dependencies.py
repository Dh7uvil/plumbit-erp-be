"""Sales invoice slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.sales_invoices.service import SalesInvoiceService


def get_sales_invoice_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> SalesInvoiceService:
    return SalesInvoiceService(session, actor_permissions=current_user.permissions)


SalesInvoiceServiceDependency = Annotated[SalesInvoiceService, Depends(get_sales_invoice_service)]

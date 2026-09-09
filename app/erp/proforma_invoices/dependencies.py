"""Proforma invoice slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.proforma_invoices.service import ProformaInvoiceService


def get_proforma_invoice_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> ProformaInvoiceService:
    return ProformaInvoiceService(session, actor_permissions=current_user.permissions)


ProformaInvoiceServiceDependency = Annotated[
    ProformaInvoiceService, Depends(get_proforma_invoice_service)
]

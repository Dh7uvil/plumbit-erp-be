"""FastAPI dependencies for invoice write-offs."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.accounting.write_offs.service import InvoiceWriteOffService


def get_invoice_write_off_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> InvoiceWriteOffService:
    return InvoiceWriteOffService(session, actor_permissions=current_user.permissions)


InvoiceWriteOffServiceDependency = Annotated[
    InvoiceWriteOffService, Depends(get_invoice_write_off_service)
]

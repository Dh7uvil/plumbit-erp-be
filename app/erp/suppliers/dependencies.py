"""Supplier slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.erp.suppliers.service import SupplierService


def get_supplier_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SupplierService:
    return SupplierService(session)


SupplierServiceDependency = Annotated[SupplierService, Depends(get_supplier_service)]

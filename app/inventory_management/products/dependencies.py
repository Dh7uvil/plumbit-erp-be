"""Product slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.inventory_management.products.service import ProductService


def get_product_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProductService:
    return ProductService(session)


ProductServiceDependency = Annotated[ProductService, Depends(get_product_service)]

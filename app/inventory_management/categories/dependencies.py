"""Category slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.inventory_management.categories.service import CategoryService


def get_category_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CategoryService:
    return CategoryService(session)


CategoryServiceDependency = Annotated[CategoryService, Depends(get_category_service)]

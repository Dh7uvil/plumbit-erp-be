"""Package slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.inventory_management.packages.service import PackageService


def get_package_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> PackageService:
    return PackageService(session, actor_permissions=current_user.permissions)


PackageServiceDependency = Annotated[PackageService, Depends(get_package_service)]

"""GL integrity slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.erp.accounting.integrity.service import GlIntegrityService


def get_gl_integrity_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> GlIntegrityService:
    return GlIntegrityService(session)


GlIntegrityServiceDependency = Annotated[GlIntegrityService, Depends(get_gl_integrity_service)]

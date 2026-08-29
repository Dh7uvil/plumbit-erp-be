"""Slice-level FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.audit_service import AuditLogService
from app.auth.org_service import OrganizationService
from app.auth.service import AuthService
from app.db.session import get_db
from app.integrations.storage.client import S3Storage, get_optional_storage


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    storage: Annotated[S3Storage | None, Depends(get_optional_storage)],
) -> AuthService:
    return AuthService(session, storage)


def get_organization_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    storage: Annotated[S3Storage | None, Depends(get_optional_storage)],
) -> OrganizationService:
    return OrganizationService(session, storage)


def get_audit_log_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuditLogService:
    return AuditLogService(session)


AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
OrganizationServiceDependency = Annotated[OrganizationService, Depends(get_organization_service)]
AuditLogServiceDependency = Annotated[AuditLogService, Depends(get_audit_log_service)]

"""Slice-level FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.audit_service import AuditLogService
from app.auth.org_service import OrganizationService
from app.auth.service import AuthService
from app.db.session import get_db


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuthService:
    return AuthService(session)


def get_organization_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> OrganizationService:
    return OrganizationService(session)


def get_audit_log_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuditLogService:
    return AuditLogService(session)


AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
OrganizationServiceDependency = Annotated[OrganizationService, Depends(get_organization_service)]
AuditLogServiceDependency = Annotated[AuditLogService, Depends(get_audit_log_service)]

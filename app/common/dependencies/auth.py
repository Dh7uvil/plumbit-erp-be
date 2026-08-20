"""Authentication dependencies built on validated access-token claims."""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.repository import AccessRepository
from app.core.config import get_settings
from app.core.enums import TenantStatus, UserStatus
from app.core.exceptions import InvalidCredentialsError, InvalidTokenError, TenantAccessDeniedError
from app.core.middleware import set_tenant_id, set_user_id
from app.core.security import decode_access_token
from app.db.session import get_db

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """Authenticated request identity with permissions loaded from the database."""

    user_id: UUID
    tenant_id: UUID | None
    permissions: frozenset[str] = frozenset()


def _parse_claim_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise InvalidTokenError() from exc


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CurrentUser:
    """Validate a bearer JWT, confirm the user is active, and load RBAC permissions."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise InvalidTokenError()

    settings = get_settings()
    claims = decode_access_token(
        credentials.credentials,
        secret=settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    user_id = _parse_claim_uuid(claims.subject)
    if user_id is None:
        raise InvalidTokenError()
    token_tenant_id = _parse_claim_uuid(claims.tenant_id)

    repo = AccessRepository(session)
    user = await repo.get_user_by_id(user_id)
    if user is None or token_tenant_id != user.tenant_id:
        raise InvalidTokenError()
    if user.status != UserStatus.ACTIVE:
        raise InvalidCredentialsError()

    tenant = await repo.get_tenant(user.tenant_id)
    if tenant is None or tenant.status != TenantStatus.ACTIVE:
        raise TenantAccessDeniedError()

    permissions = await repo.list_user_permission_strings(user.tenant_id, user.id)
    set_user_id(str(user.id))
    set_tenant_id(str(user.tenant_id))
    return CurrentUser(
        user_id=user.id,
        tenant_id=user.tenant_id,
        permissions=permissions,
    )


CurrentUserDependency = Annotated[CurrentUser, Depends(get_current_user)]

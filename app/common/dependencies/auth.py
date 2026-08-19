"""Authentication dependencies built on validated access-token claims."""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.core.exceptions import InvalidTokenError
from app.core.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """Authenticated request identity.

    Permissions remain empty until the users-management module loads them from
    the database. This extension point fails closed in the foundation layer.
    """

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
) -> CurrentUser:
    """Validate a bearer JWT and derive an immutable request identity."""

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

    return CurrentUser(
        user_id=user_id,
        tenant_id=_parse_claim_uuid(claims.tenant_id),
    )


CurrentUserDependency = Annotated[CurrentUser, Depends(get_current_user)]

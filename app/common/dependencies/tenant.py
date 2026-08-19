"""Tenant context derived exclusively from authenticated identity."""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends

from app.common.dependencies.auth import CurrentUser, get_current_user
from app.core.exceptions import TenantAccessDeniedError


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Trusted tenant and user identifiers for a request."""

    tenant_id: UUID
    user_id: UUID


async def get_tenant_context(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> TenantContext:
    """Resolve tenant context from verified JWT-derived identity only."""

    if current_user.tenant_id is None:
        raise TenantAccessDeniedError()
    return TenantContext(
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
    )


TenantContextDependency = Annotated[TenantContext, Depends(get_tenant_context)]

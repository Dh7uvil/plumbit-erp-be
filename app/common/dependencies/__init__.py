"""Shared FastAPI dependency exports."""

from app.common.dependencies.auth import (
    CurrentUser,
    CurrentUserDependency,
    get_current_user,
)
from app.common.dependencies.pagination import (
    PaginationDependency,
    get_page_params,
)
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import (
    TenantContext,
    TenantContextDependency,
    get_tenant_context,
)

__all__ = [
    "CurrentUser",
    "CurrentUserDependency",
    "PaginationDependency",
    "TenantContext",
    "TenantContextDependency",
    "get_current_user",
    "get_page_params",
    "get_tenant_context",
    "require_permission",
]

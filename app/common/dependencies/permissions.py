"""Permission-enforcement dependency factory."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends

from app.common.dependencies.auth import CurrentUser, get_current_user
from app.core.exceptions import PermissionDeniedError
from app.core.permissions import has_permission, parse_permission

PermissionDependency = Callable[[CurrentUser], Awaitable[CurrentUser]]


def require_permission(required_permission: str) -> PermissionDependency:
    """Build a dependency that fails closed without the required permission."""

    parsed_permission = parse_permission(required_permission)

    async def dependency(
        current_user: Annotated[CurrentUser, Depends(get_current_user)],
    ) -> CurrentUser:
        if not has_permission(current_user.permissions, parsed_permission):
            raise PermissionDeniedError()
        return current_user

    return dependency

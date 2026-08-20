"""HTTP routes for tenant discovery, authentication, and access management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import (
    PERMISSION_READ,
    ROLE_CREATE,
    ROLE_DELETE,
    ROLE_READ,
    ROLE_UPDATE,
    USER_CREATE,
    USER_DELETE,
    USER_READ,
    USER_UPDATE,
)
from app.auth.dependencies import AuthServiceDependency
from app.auth.schemas import (
    AssignRolesRequest,
    ChangePasswordRequest,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    PermissionFilter,
    PermissionResponse,
    RefreshRequest,
    RoleCreate,
    RoleDetailResponse,
    RoleFilter,
    RoleResponse,
    RoleUpdate,
    SetRolePermissionsRequest,
    TenantPublicResponse,
    TokenPairResponse,
    UserCreate,
    UserDetailResponse,
    UserFilter,
    UserResponse,
    UserUpdate,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse

router = APIRouter()

tenants_router = APIRouter(prefix="/tenants", tags=["Tenants"])
auth_router = APIRouter(prefix="/auth", tags=["Auth"])
users_router = APIRouter(prefix="/users", tags=["Users"])
roles_router = APIRouter(prefix="/roles", tags=["Roles"])
permissions_router = APIRouter(prefix="/permissions", tags=["Permissions"])


@tenants_router.get(
    "",
    response_model=ApiResponse[list[TenantPublicResponse]],
    summary="List active tenants",
    description="Public tenant list for the login-screen selector.",
)
async def list_tenants(service: AuthServiceDependency) -> ApiResponse[list[TenantPublicResponse]]:
    tenants = await service.list_active_tenants()
    return ApiResponse(data=tenants)


@auth_router.post(
    "/login",
    response_model=ApiResponse[TokenPairResponse],
    summary="Log in",
    description="Authenticate with tenant, email, and password, then issue tokens.",
)
async def login(
    payload: LoginRequest,
    service: AuthServiceDependency,
) -> ApiResponse[TokenPairResponse]:
    tokens = await service.login(payload)
    return ApiResponse(data=tokens, message="Logged in successfully")


@auth_router.post(
    "/refresh",
    response_model=ApiResponse[TokenPairResponse],
    summary="Refresh session",
    description="Rotate a refresh token and issue a new access/refresh token pair.",
)
async def refresh(
    payload: RefreshRequest,
    service: AuthServiceDependency,
) -> ApiResponse[TokenPairResponse]:
    tokens = await service.refresh(payload.refresh_token)
    return ApiResponse(data=tokens)


@auth_router.post(
    "/logout",
    response_model=ApiResponse[None],
    summary="Log out",
    description="Revoke the presented refresh token for the authenticated user.",
)
async def logout(
    payload: LogoutRequest,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
) -> ApiResponse[None]:
    await service.logout(
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        refresh_token=payload.refresh_token,
    )
    return ApiResponse(data=None, message="Logged out successfully")


@auth_router.get(
    "/me",
    response_model=ApiResponse[MeResponse],
    summary="Current user",
    description="Return the authenticated user, assigned roles, and granted permissions.",
)
async def me(
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
) -> ApiResponse[MeResponse]:
    data = await service.me(tenant_id=tenant.tenant_id, user_id=tenant.user_id)
    return ApiResponse(data=data)


@auth_router.post(
    "/change-password",
    response_model=ApiResponse[TokenPairResponse],
    summary="Change password",
    description="Update the password, revoke other sessions, and return a new token pair.",
)
async def change_password(
    payload: ChangePasswordRequest,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
) -> ApiResponse[TokenPairResponse]:
    tokens = await service.change_password(
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        payload=payload,
    )
    return ApiResponse(data=tokens, message="Password changed successfully")


@users_router.get(
    "",
    response_model=ApiResponse[list[UserResponse]],
    summary="List users",
)
async def list_users(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: AuthServiceDependency,
    filters: Annotated[UserFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(USER_READ))],
) -> ApiResponse[list[UserResponse]]:
    users, total = await service.list_users(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status is not None else None,
    )
    return paginated_response(users, params=page, total=total)


@users_router.post(
    "",
    response_model=ApiResponse[UserDetailResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create user",
)
async def create_user(
    payload: UserCreate,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(USER_CREATE))],
) -> ApiResponse[UserDetailResponse]:
    user = await service.create_user(tenant.tenant_id, payload)
    return ApiResponse(data=user, message="User created successfully")


@users_router.get(
    "/{user_id}",
    response_model=ApiResponse[UserDetailResponse],
    summary="Get user",
)
async def get_user(
    user_id: UUID,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(USER_READ))],
) -> ApiResponse[UserDetailResponse]:
    user = await service.get_user(tenant.tenant_id, user_id)
    return ApiResponse(data=user)


@users_router.patch(
    "/{user_id}",
    response_model=ApiResponse[UserDetailResponse],
    summary="Update user",
)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(USER_UPDATE))],
) -> ApiResponse[UserDetailResponse]:
    user = await service.update_user(
        tenant.tenant_id,
        user_id,
        payload,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=user, message="User updated successfully")


@users_router.post(
    "/{user_id}/deactivate",
    response_model=ApiResponse[UserDetailResponse],
    summary="Deactivate user",
)
async def deactivate_user(
    user_id: UUID,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(USER_DELETE))],
) -> ApiResponse[UserDetailResponse]:
    user = await service.deactivate_user(
        tenant.tenant_id,
        user_id,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=user, message="User deactivated successfully")


@users_router.put(
    "/{user_id}/roles",
    response_model=ApiResponse[UserDetailResponse],
    summary="Assign user roles",
)
async def assign_user_roles(
    user_id: UUID,
    payload: AssignRolesRequest,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(USER_UPDATE))],
) -> ApiResponse[UserDetailResponse]:
    user = await service.assign_roles(tenant.tenant_id, user_id, payload)
    return ApiResponse(data=user, message="User roles updated successfully")


@roles_router.get(
    "",
    response_model=ApiResponse[list[RoleResponse]],
    summary="List roles",
)
async def list_roles(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: AuthServiceDependency,
    filters: Annotated[RoleFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(ROLE_READ))],
) -> ApiResponse[list[RoleResponse]]:
    roles, total = await service.list_roles(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
    )
    return paginated_response(roles, params=page, total=total)


@roles_router.post(
    "",
    response_model=ApiResponse[RoleDetailResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create role",
)
async def create_role(
    payload: RoleCreate,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ROLE_CREATE))],
) -> ApiResponse[RoleDetailResponse]:
    role = await service.create_role(tenant.tenant_id, payload)
    return ApiResponse(data=role, message="Role created successfully")


@roles_router.get(
    "/{role_id}",
    response_model=ApiResponse[RoleDetailResponse],
    summary="Get role",
)
async def get_role(
    role_id: UUID,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ROLE_READ))],
) -> ApiResponse[RoleDetailResponse]:
    role = await service.get_role(tenant.tenant_id, role_id)
    return ApiResponse(data=role)


@roles_router.patch(
    "/{role_id}",
    response_model=ApiResponse[RoleDetailResponse],
    summary="Update role",
)
async def update_role(
    role_id: UUID,
    payload: RoleUpdate,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ROLE_UPDATE))],
) -> ApiResponse[RoleDetailResponse]:
    role = await service.update_role(tenant.tenant_id, role_id, payload)
    return ApiResponse(data=role, message="Role updated successfully")


@roles_router.delete(
    "/{role_id}",
    response_model=ApiResponse[RoleResponse],
    summary="Delete role",
)
async def delete_role(
    role_id: UUID,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ROLE_DELETE))],
) -> ApiResponse[RoleResponse]:
    role = await service.delete_role(tenant.tenant_id, role_id)
    return ApiResponse(data=role, message="Role deleted successfully")


@roles_router.put(
    "/{role_id}/permissions",
    response_model=ApiResponse[RoleDetailResponse],
    summary="Set role permissions",
)
async def set_role_permissions(
    role_id: UUID,
    payload: SetRolePermissionsRequest,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ROLE_UPDATE))],
) -> ApiResponse[RoleDetailResponse]:
    role = await service.set_role_permissions(tenant.tenant_id, role_id, payload)
    return ApiResponse(data=role, message="Role permissions updated successfully")


@permissions_router.get(
    "",
    response_model=ApiResponse[list[PermissionResponse]],
    summary="List permissions",
)
async def list_permissions(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: AuthServiceDependency,
    filters: Annotated[PermissionFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(PERMISSION_READ))],
) -> ApiResponse[list[PermissionResponse]]:
    permissions, total = await service.list_permissions(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        module=filters.module,
    )
    return paginated_response(permissions, params=page, total=total)


router.include_router(tenants_router)
router.include_router(auth_router)
router.include_router(users_router)
router.include_router(roles_router)
router.include_router(permissions_router)

"""HTTP routes for tenant discovery, authentication, and access management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.auth.catalog import (
    AUDIT_LOG_READ,
    BRANCH_CREATE,
    BRANCH_DELETE,
    BRANCH_READ,
    BRANCH_UPDATE,
    DEPARTMENT_CREATE,
    DEPARTMENT_DELETE,
    DEPARTMENT_READ,
    DEPARTMENT_UPDATE,
    ORGANIZATION_READ,
    ORGANIZATION_UPDATE,
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
from app.auth.dependencies import (
    AuditLogServiceDependency,
    AuthServiceDependency,
    OrganizationServiceDependency,
)
from app.auth.org_service import LOGO_MAX_SIZE_MB
from app.auth.schemas import (
    AssignRolesRequest,
    AuditLogFilter,
    AuditLogResponse,
    AuditLogSummaryResponse,
    BranchCreate,
    BranchFilter,
    BranchResponse,
    BranchUpdate,
    ChangePasswordRequest,
    DepartmentCreate,
    DepartmentFilter,
    DepartmentResponse,
    DepartmentUpdate,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    PermissionFilter,
    PermissionMatrixResponse,
    PermissionResponse,
    RefreshRequest,
    RoleCreate,
    RoleDetailResponse,
    RoleFilter,
    RoleResponse,
    RoleUpdate,
    SetRolePermissionsRequest,
    TenantCurrentResponse,
    TenantCurrentUpdate,
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
from app.common.utils.files import max_upload_bytes
from app.core.exceptions import ValidationError

router = APIRouter()

tenants_router = APIRouter(prefix="/tenants", tags=["Tenants"])
auth_router = APIRouter(prefix="/auth", tags=["Auth"])
users_router = APIRouter(prefix="/users", tags=["Users"])
roles_router = APIRouter(prefix="/roles", tags=["Roles"])
permissions_router = APIRouter(prefix="/permissions", tags=["Permissions"])
branches_router = APIRouter(prefix="/branches", tags=["Branches"])
departments_router = APIRouter(prefix="/departments", tags=["Departments"])
audit_logs_router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


@tenants_router.get(
    "",
    response_model=ApiResponse[list[TenantPublicResponse]],
    summary="List active tenants",
    description="Public tenant list for the login-screen selector.",
)
async def list_tenants(service: AuthServiceDependency) -> ApiResponse[list[TenantPublicResponse]]:
    tenants = await service.list_active_tenants()
    return ApiResponse(data=tenants)


@tenants_router.get(
    "/current",
    response_model=ApiResponse[TenantCurrentResponse],
    summary="Get current organization",
    description="Requires `identity.organization.read`. Tenant is taken from the session.",
)
async def get_current_tenant(
    tenant: TenantContextDependency,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ORGANIZATION_READ))],
) -> ApiResponse[TenantCurrentResponse]:
    data = await service.get_current_tenant(tenant.tenant_id)
    return ApiResponse(data=data)


@tenants_router.patch(
    "/current",
    response_model=ApiResponse[TenantCurrentResponse],
    summary="Update current organization",
    description="Requires `identity.organization.update`. Tenant is taken from the session.",
)
async def update_current_tenant(
    payload: TenantCurrentUpdate,
    tenant: TenantContextDependency,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ORGANIZATION_UPDATE))],
) -> ApiResponse[TenantCurrentResponse]:
    data = await service.update_current_tenant(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=data, message="Organization updated successfully")


@tenants_router.post(
    "/current/logo",
    response_model=ApiResponse[TenantCurrentResponse],
    summary="Upload current organization logo",
    description=(
        "Requires `identity.organization.update`. Replaces the existing logo if one is set."
    ),
)
async def upload_current_tenant_logo(
    tenant: TenantContextDependency,
    service: OrganizationServiceDependency,
    file: Annotated[UploadFile, File()],
    _: Annotated[CurrentUser, Depends(require_permission(ORGANIZATION_UPDATE))],
) -> ApiResponse[TenantCurrentResponse]:
    content = await _read_upload(file, max_bytes=max_upload_bytes(LOGO_MAX_SIZE_MB))
    data = await service.upload_logo(
        tenant.tenant_id,
        filename=file.filename,
        content=content,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=data, message="Organization logo updated successfully")


@tenants_router.delete(
    "/current/logo",
    response_model=ApiResponse[TenantCurrentResponse],
    summary="Delete current organization logo",
    description="Requires `identity.organization.update`.",
)
async def delete_current_tenant_logo(
    tenant: TenantContextDependency,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ORGANIZATION_UPDATE))],
) -> ApiResponse[TenantCurrentResponse]:
    data = await service.delete_logo(tenant.tenant_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=data, message="Organization logo deleted successfully")


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
    description="Return the authenticated user, roles, nested employee, and permissions.",
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
    description=(
        "Requires `identity.user.read`. Rows include roles and nested employee. "
        "Filter by account status, roles, phone, last login, and employee fields "
        "(department, branch, designation, joining date, employee status, employee code, manager)."
    ),
)
async def list_users(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: AuthServiceDependency,
    filters: Annotated[UserFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(USER_READ))],
    role_ids: Annotated[
        list[UUID] | None,
        Query(
            description=(
                "Users assigned to any of these roles. Repeat the parameter for multiple roles."
            )
        ),
    ] = None,
) -> ApiResponse[list[UserResponse]]:
    user_filter = filters
    if role_ids:
        user_filter = filters.model_copy(
            update={
                "role_ids": list(dict.fromkeys([*(filters.role_ids or []), *role_ids])),
            }
        )
    users, total = await service.list_users(
        tenant.tenant_id,
        page=page,
        user_filter=user_filter,
    )
    return paginated_response(users, params=page, total=total)


@users_router.post(
    "",
    response_model=ApiResponse[UserDetailResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create user",
    description="Requires `identity.user.create`. Optional nested `employee` HR profile.",
)
async def create_user(
    payload: UserCreate,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(USER_CREATE))],
) -> ApiResponse[UserDetailResponse]:
    user = await service.create_user(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=user, message="User created successfully")


@users_router.get(
    "/{user_id}",
    response_model=ApiResponse[UserDetailResponse],
    summary="Get user",
    description="Requires `identity.user.read`.",
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
    description="Requires `identity.user.update`. Optional nested `employee` HR profile.",
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
    description="Requires `identity.user.delete`. Disables the account; no hard delete.",
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


@users_router.post(
    "/{user_id}/activate",
    response_model=ApiResponse[UserDetailResponse],
    summary="Activate user",
    description="Requires `identity.user.update`. Restores a disabled user to active.",
)
async def activate_user(
    user_id: UUID,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(USER_UPDATE))],
) -> ApiResponse[UserDetailResponse]:
    user = await service.activate_user(
        tenant.tenant_id,
        user_id,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=user, message="User activated successfully")


@users_router.put(
    "/{user_id}/roles",
    response_model=ApiResponse[UserDetailResponse],
    summary="Assign user roles",
    description="Requires `identity.user.update`.",
)
async def assign_user_roles(
    user_id: UUID,
    payload: AssignRolesRequest,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(USER_UPDATE))],
) -> ApiResponse[UserDetailResponse]:
    user = await service.assign_roles(
        tenant.tenant_id,
        user_id,
        payload,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=user, message="User roles updated successfully")


@roles_router.get(
    "",
    response_model=ApiResponse[list[RoleResponse]],
    summary="List roles",
    description="Requires `identity.role.read`. Each row includes `user_count`.",
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
    description="Requires `identity.role.create`.",
)
async def create_role(
    payload: RoleCreate,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ROLE_CREATE))],
) -> ApiResponse[RoleDetailResponse]:
    role = await service.create_role(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=role, message="Role created successfully")


@roles_router.get(
    "/{role_id}",
    response_model=ApiResponse[RoleDetailResponse],
    summary="Get role",
    description="Requires `identity.role.read`.",
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
    description="Requires `identity.role.update`.",
)
async def update_role(
    role_id: UUID,
    payload: RoleUpdate,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ROLE_UPDATE))],
) -> ApiResponse[RoleDetailResponse]:
    role = await service.update_role(
        tenant.tenant_id,
        role_id,
        payload,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=role, message="Role updated successfully")


@roles_router.delete(
    "/{role_id}",
    response_model=ApiResponse[RoleResponse],
    summary="Delete role",
    description="Requires `identity.role.delete`. System roles cannot be deleted.",
)
async def delete_role(
    role_id: UUID,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ROLE_DELETE))],
) -> ApiResponse[RoleResponse]:
    role = await service.delete_role(
        tenant.tenant_id,
        role_id,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=role, message="Role deleted successfully")


@roles_router.put(
    "/{role_id}/permissions",
    response_model=ApiResponse[RoleDetailResponse],
    summary="Set role permissions",
    description="Requires `identity.role.update`.",
)
async def set_role_permissions(
    role_id: UUID,
    payload: SetRolePermissionsRequest,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ROLE_UPDATE))],
) -> ApiResponse[RoleDetailResponse]:
    role = await service.set_role_permissions(
        tenant.tenant_id,
        role_id,
        payload,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=role, message="Role permissions updated successfully")


@roles_router.post(
    "/{role_id}/permissions/reset",
    response_model=ApiResponse[RoleDetailResponse],
    summary="Reset Superadmin role permissions",
    description=(
        "Requires `identity.role.update`. Restores the system Superadmin role to the full "
        "seeded catalog. Non-system roles are rejected."
    ),
)
async def reset_role_permissions(
    role_id: UUID,
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ROLE_UPDATE))],
) -> ApiResponse[RoleDetailResponse]:
    role = await service.reset_role_permissions(
        tenant.tenant_id,
        role_id,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=role, message="Role permissions reset successfully")


@permissions_router.get(
    "/matrix",
    response_model=ApiResponse[PermissionMatrixResponse],
    summary="Permission matrix",
    description=(
        "Requires `identity.permission.read`. Catalog grouped by module and resource. "
        "Omit `role_id` to return every action with `granted: false`."
    ),
)
async def permission_matrix(
    tenant: TenantContextDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PERMISSION_READ))],
    role_id: Annotated[UUID | None, Query()] = None,
) -> ApiResponse[PermissionMatrixResponse]:
    data = await service.permission_matrix(tenant.tenant_id, role_id=role_id)
    return ApiResponse(data=data)


@permissions_router.get(
    "",
    response_model=ApiResponse[list[PermissionResponse]],
    summary="List permissions",
    description=(
        "Requires `identity.permission.read`. Codes use `identity.<resource>.<action>` "
        "(for example `identity.user.read`)."
    ),
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


@branches_router.get(
    "",
    response_model=ApiResponse[list[BranchResponse]],
    summary="List branches",
    description="Requires `identity.branch.read`.",
)
async def list_branches(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: OrganizationServiceDependency,
    filters: Annotated[BranchFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(BRANCH_READ))],
) -> ApiResponse[list[BranchResponse]]:
    branches, total = await service.list_branches(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status is not None else None,
    )
    return paginated_response(branches, params=page, total=total)


@branches_router.post(
    "",
    response_model=ApiResponse[BranchResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create branch",
    description="Requires `identity.branch.create`.",
)
async def create_branch(
    payload: BranchCreate,
    tenant: TenantContextDependency,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BRANCH_CREATE))],
) -> ApiResponse[BranchResponse]:
    branch = await service.create_branch(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=branch, message="Branch created successfully")


@branches_router.get(
    "/{branch_id}",
    response_model=ApiResponse[BranchResponse],
    summary="Get branch",
    description="Requires `identity.branch.read`.",
)
async def get_branch(
    branch_id: UUID,
    tenant: TenantContextDependency,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BRANCH_READ))],
) -> ApiResponse[BranchResponse]:
    branch = await service.get_branch(tenant.tenant_id, branch_id)
    return ApiResponse(data=branch)


@branches_router.patch(
    "/{branch_id}",
    response_model=ApiResponse[BranchResponse],
    summary="Update branch",
    description="Requires `identity.branch.update`.",
)
async def update_branch(
    branch_id: UUID,
    payload: BranchUpdate,
    tenant: TenantContextDependency,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BRANCH_UPDATE))],
) -> ApiResponse[BranchResponse]:
    branch = await service.update_branch(
        tenant.tenant_id,
        branch_id,
        payload,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=branch, message="Branch updated successfully")


@branches_router.delete(
    "/{branch_id}",
    response_model=ApiResponse[BranchResponse],
    summary="Delete branch",
    description="Requires `identity.branch.delete`. Soft-deletes the branch.",
)
async def delete_branch(
    branch_id: UUID,
    tenant: TenantContextDependency,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BRANCH_DELETE))],
) -> ApiResponse[BranchResponse]:
    branch = await service.delete_branch(
        tenant.tenant_id,
        branch_id,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=branch, message="Branch deleted successfully")


@departments_router.get(
    "",
    response_model=ApiResponse[list[DepartmentResponse]],
    summary="List departments",
    description="Requires `identity.department.read`.",
)
async def list_departments(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: OrganizationServiceDependency,
    filters: Annotated[DepartmentFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(DEPARTMENT_READ))],
) -> ApiResponse[list[DepartmentResponse]]:
    departments, total = await service.list_departments(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        branch_id=filters.branch_id,
    )
    return paginated_response(departments, params=page, total=total)


@departments_router.post(
    "",
    response_model=ApiResponse[DepartmentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create department",
    description="Requires `identity.department.create`.",
)
async def create_department(
    payload: DepartmentCreate,
    tenant: TenantContextDependency,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DEPARTMENT_CREATE))],
) -> ApiResponse[DepartmentResponse]:
    department = await service.create_department(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=department, message="Department created successfully")


@departments_router.get(
    "/{department_id}",
    response_model=ApiResponse[DepartmentResponse],
    summary="Get department",
    description="Requires `identity.department.read`.",
)
async def get_department(
    department_id: UUID,
    tenant: TenantContextDependency,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DEPARTMENT_READ))],
) -> ApiResponse[DepartmentResponse]:
    department = await service.get_department(tenant.tenant_id, department_id)
    return ApiResponse(data=department)


@departments_router.patch(
    "/{department_id}",
    response_model=ApiResponse[DepartmentResponse],
    summary="Update department",
    description="Requires `identity.department.update`.",
)
async def update_department(
    department_id: UUID,
    payload: DepartmentUpdate,
    tenant: TenantContextDependency,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DEPARTMENT_UPDATE))],
) -> ApiResponse[DepartmentResponse]:
    department = await service.update_department(
        tenant.tenant_id,
        department_id,
        payload,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=department, message="Department updated successfully")


@departments_router.delete(
    "/{department_id}",
    response_model=ApiResponse[DepartmentResponse],
    summary="Delete department",
    description="Requires `identity.department.delete`. Soft-deletes the department.",
)
async def delete_department(
    department_id: UUID,
    tenant: TenantContextDependency,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DEPARTMENT_DELETE))],
) -> ApiResponse[DepartmentResponse]:
    department = await service.delete_department(
        tenant.tenant_id,
        department_id,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=department, message="Department deleted successfully")


@audit_logs_router.get(
    "/summary",
    response_model=ApiResponse[AuditLogSummaryResponse],
    summary="Audit log summary",
    description="Requires `identity.audit_log.read`. KPI counts for the Audit Logs page.",
)
async def audit_log_summary(
    tenant: TenantContextDependency,
    service: AuditLogServiceDependency,
    filters: Annotated[AuditLogFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(AUDIT_LOG_READ))],
) -> ApiResponse[AuditLogSummaryResponse]:
    data = await service.summarize(tenant.tenant_id, common_filter=filters)
    return ApiResponse(data=data)


@audit_logs_router.get(
    "",
    response_model=ApiResponse[list[AuditLogResponse]],
    summary="List audit logs",
    description="Requires `identity.audit_log.read`. Append-only; there is no update or delete.",
)
async def list_audit_logs(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: AuditLogServiceDependency,
    filters: Annotated[AuditLogFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(AUDIT_LOG_READ))],
) -> ApiResponse[list[AuditLogResponse]]:
    rows, total = await service.list_logs(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        module=filters.module,
        action=filters.action,
        user_id=filters.user_id,
    )
    return paginated_response(rows, params=page, total=total)


_READ_CHUNK_SIZE = 64 * 1024


async def _read_upload(file: UploadFile, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_READ_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValidationError(
                "File exceeds the maximum upload size",
                details={"max_bytes": max_bytes},
            )
        chunks.append(chunk)
    return b"".join(chunks)


router.include_router(tenants_router)
router.include_router(auth_router)
router.include_router(users_router)
router.include_router(roles_router)
router.include_router(permissions_router)
router.include_router(branches_router)
router.include_router(departments_router)
router.include_router(audit_logs_router)

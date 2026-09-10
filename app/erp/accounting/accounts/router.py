"""Chart of accounts routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import ACCOUNT_CREATE, ACCOUNT_DELETE, ACCOUNT_READ, ACCOUNT_UPDATE
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.core.enums import AccountSystemRole
from app.erp.accounting.accounts.dependencies import AccountServiceDependency
from app.erp.accounting.accounts.schemas import (
    AccountCreate,
    AccountFilter,
    AccountResponse,
    AccountTreeNode,
    AccountUpdate,
    SystemRoleMapping,
    SystemRoleUpdate,
)

router = APIRouter(prefix="/accounts", tags=["Accounts"])


@router.get("", response_model=ApiResponse[list[AccountResponse]])
async def list_accounts(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: AccountServiceDependency,
    filters: Annotated[AccountFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(ACCOUNT_READ))],
) -> ApiResponse[list[AccountResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        account_type=filters.account_type.value if filters.account_type else None,
        account_subtype=filters.account_subtype.value if filters.account_subtype else None,
        is_group=filters.is_group,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


@router.get("/tree", response_model=ApiResponse[list[AccountTreeNode]])
async def get_account_tree(
    tenant: TenantContextDependency,
    service: AccountServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ACCOUNT_READ))],
) -> ApiResponse[list[AccountTreeNode]]:
    return ApiResponse(data=await service.tree(tenant.tenant_id))


@router.get("/system-roles", response_model=ApiResponse[list[SystemRoleMapping]])
async def list_system_roles(
    tenant: TenantContextDependency,
    service: AccountServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ACCOUNT_READ))],
) -> ApiResponse[list[SystemRoleMapping]]:
    return ApiResponse(data=await service.list_system_roles(tenant.tenant_id))


@router.put("/system-roles/{role}", response_model=ApiResponse[SystemRoleMapping])
async def map_system_role(
    role: AccountSystemRole,
    payload: SystemRoleUpdate,
    tenant: TenantContextDependency,
    service: AccountServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ACCOUNT_UPDATE))],
) -> ApiResponse[SystemRoleMapping]:
    row = await service.map_system_role(
        tenant.tenant_id, role, payload.account_id, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="System role mapped")


@router.post("", response_model=ApiResponse[AccountResponse], status_code=status.HTTP_201_CREATED)
async def create_account(
    payload: AccountCreate,
    tenant: TenantContextDependency,
    service: AccountServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ACCOUNT_CREATE))],
) -> ApiResponse[AccountResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Account created successfully")


@router.get("/{account_id}", response_model=ApiResponse[AccountResponse])
async def get_account(
    account_id: UUID,
    tenant: TenantContextDependency,
    service: AccountServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ACCOUNT_READ))],
) -> ApiResponse[AccountResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, account_id))


@router.patch("/{account_id}", response_model=ApiResponse[AccountResponse])
async def update_account(
    account_id: UUID,
    payload: AccountUpdate,
    tenant: TenantContextDependency,
    service: AccountServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ACCOUNT_UPDATE))],
) -> ApiResponse[AccountResponse]:
    row = await service.update(
        tenant.tenant_id, account_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Account updated successfully")


@router.delete("/{account_id}", response_model=ApiResponse[AccountResponse])
async def delete_account(
    account_id: UUID,
    tenant: TenantContextDependency,
    service: AccountServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ACCOUNT_DELETE))],
) -> ApiResponse[AccountResponse]:
    row = await service.delete(tenant.tenant_id, account_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Account deleted successfully")

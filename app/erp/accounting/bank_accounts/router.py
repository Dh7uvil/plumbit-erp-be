"""Bank account routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import (
    BANK_ACCOUNT_CREATE,
    BANK_ACCOUNT_DELETE,
    BANK_ACCOUNT_READ,
    BANK_ACCOUNT_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.erp.accounting.bank_accounts.dependencies import BankAccountServiceDependency
from app.erp.accounting.bank_accounts.schemas import (
    BankAccountCreate,
    BankAccountFilter,
    BankAccountResponse,
    BankAccountUpdate,
)

router = APIRouter(prefix="/bank-accounts", tags=["Bank Accounts"])


@router.get("", response_model=ApiResponse[list[BankAccountResponse]])
async def list_bank_accounts(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: BankAccountServiceDependency,
    filters: Annotated[BankAccountFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(BANK_ACCOUNT_READ))],
) -> ApiResponse[list[BankAccountResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        is_active=filters.is_active,
        currency_id=filters.currency_id,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[BankAccountResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_bank_account(
    payload: BankAccountCreate,
    tenant: TenantContextDependency,
    service: BankAccountServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BANK_ACCOUNT_CREATE))],
) -> ApiResponse[BankAccountResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Bank account created successfully")


@router.get("/{bank_account_id}", response_model=ApiResponse[BankAccountResponse])
async def get_bank_account(
    bank_account_id: UUID,
    tenant: TenantContextDependency,
    service: BankAccountServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BANK_ACCOUNT_READ))],
) -> ApiResponse[BankAccountResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, bank_account_id))


@router.patch("/{bank_account_id}", response_model=ApiResponse[BankAccountResponse])
async def update_bank_account(
    bank_account_id: UUID,
    payload: BankAccountUpdate,
    tenant: TenantContextDependency,
    service: BankAccountServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BANK_ACCOUNT_UPDATE))],
) -> ApiResponse[BankAccountResponse]:
    row = await service.update(
        tenant.tenant_id, bank_account_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Bank account updated successfully")


@router.delete("/{bank_account_id}", response_model=ApiResponse[BankAccountResponse])
async def delete_bank_account(
    bank_account_id: UUID,
    tenant: TenantContextDependency,
    service: BankAccountServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BANK_ACCOUNT_DELETE))],
) -> ApiResponse[BankAccountResponse]:
    row = await service.delete(tenant.tenant_id, bank_account_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Bank account deleted successfully")

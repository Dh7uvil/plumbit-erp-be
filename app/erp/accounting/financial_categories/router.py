"""Financial category routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import (
    FINANCIAL_CATEGORY_CREATE,
    FINANCIAL_CATEGORY_DELETE,
    FINANCIAL_CATEGORY_READ,
    FINANCIAL_CATEGORY_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.erp.accounting.financial_categories.dependencies import FinancialCategoryServiceDependency
from app.erp.accounting.financial_categories.schemas import (
    FinancialCategoryCreate,
    FinancialCategoryFilter,
    FinancialCategoryResponse,
    FinancialCategoryUpdate,
)

router = APIRouter(prefix="/financial-categories", tags=["Financial Categories"])


@router.get("", response_model=ApiResponse[list[FinancialCategoryResponse]])
async def list_financial_categories(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: FinancialCategoryServiceDependency,
    filters: Annotated[FinancialCategoryFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(FINANCIAL_CATEGORY_READ))],
) -> ApiResponse[list[FinancialCategoryResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        account_type=filters.account_type,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[FinancialCategoryResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_financial_category(
    payload: FinancialCategoryCreate,
    tenant: TenantContextDependency,
    service: FinancialCategoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(FINANCIAL_CATEGORY_CREATE))],
) -> ApiResponse[FinancialCategoryResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Financial category created successfully")


@router.get("/{category_id}", response_model=ApiResponse[FinancialCategoryResponse])
async def get_financial_category(
    category_id: UUID,
    tenant: TenantContextDependency,
    service: FinancialCategoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(FINANCIAL_CATEGORY_READ))],
) -> ApiResponse[FinancialCategoryResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, category_id))


@router.patch("/{category_id}", response_model=ApiResponse[FinancialCategoryResponse])
async def update_financial_category(
    category_id: UUID,
    payload: FinancialCategoryUpdate,
    tenant: TenantContextDependency,
    service: FinancialCategoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(FINANCIAL_CATEGORY_UPDATE))],
) -> ApiResponse[FinancialCategoryResponse]:
    row = await service.update(
        tenant.tenant_id, category_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Financial category updated successfully")


@router.delete("/{category_id}", response_model=ApiResponse[FinancialCategoryResponse])
async def delete_financial_category(
    category_id: UUID,
    tenant: TenantContextDependency,
    service: FinancialCategoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(FINANCIAL_CATEGORY_DELETE))],
) -> ApiResponse[FinancialCategoryResponse]:
    row = await service.delete(tenant.tenant_id, category_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Financial category deleted successfully")

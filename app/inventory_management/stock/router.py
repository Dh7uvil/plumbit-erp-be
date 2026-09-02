"""Stock inquiry routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.catalog import STOCK_READ, STOCK_UPDATE
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.inventory_management.stock.dependencies import StockServiceDependency
from app.inventory_management.stock.schemas import (
    StockBalanceResponse,
    StockFilter,
    StockMovementFilter,
    StockMovementResponse,
    StockReorderUpdate,
)

router = APIRouter(tags=["Stock"])


@router.get("/stock", response_model=ApiResponse[list[StockBalanceResponse]])
async def list_stock(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: StockServiceDependency,
    filters: Annotated[StockFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(STOCK_READ))],
) -> ApiResponse[list[StockBalanceResponse]]:
    rows, total = await service.list_balances(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        warehouse_id=filters.warehouse_id,
        product_id=filters.product_id,
        category_id=filters.category_id,
        negative_only=filters.negative_only,
        below_reorder=filters.below_reorder,
    )
    return paginated_response(rows, params=page, total=total)


@router.get("/stock-movements", response_model=ApiResponse[list[StockMovementResponse]])
async def list_stock_movements(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: StockServiceDependency,
    filters: Annotated[StockMovementFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(STOCK_READ))],
) -> ApiResponse[list[StockMovementResponse]]:
    rows, total = await service.list_movements(tenant.tenant_id, page=page, filters=filters)
    return paginated_response(rows, params=page, total=total)


@router.patch("/stock/{balance_id}/reorder", response_model=ApiResponse[StockBalanceResponse])
async def update_stock_reorder(
    balance_id: UUID,
    payload: StockReorderUpdate,
    tenant: TenantContextDependency,
    service: StockServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(STOCK_UPDATE))],
) -> ApiResponse[StockBalanceResponse]:
    row = await service.update_reorder(
        tenant.tenant_id, balance_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Reorder levels updated successfully")

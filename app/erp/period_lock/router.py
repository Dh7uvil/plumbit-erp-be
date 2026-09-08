"""Transaction lock and books-close routes."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth.catalog import ORGANIZATION_READ, PERIOD_LOCK
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.response import ApiResponse
from app.erp.period_lock.dependencies import PeriodLockServiceDependency
from app.erp.period_lock.schemas import (
    PeriodLockPreviewResponse,
    PeriodLockResponse,
    PeriodLockUpdate,
)

router = APIRouter(prefix="/period-lock", tags=["Period Lock"])


@router.get("", response_model=ApiResponse[PeriodLockResponse])
async def get_period_lock(
    tenant: TenantContextDependency,
    service: PeriodLockServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ORGANIZATION_READ))],
) -> ApiResponse[PeriodLockResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id))


@router.get("/preview", response_model=ApiResponse[PeriodLockPreviewResponse])
async def preview_period_lock(
    tenant: TenantContextDependency,
    service: PeriodLockServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PERIOD_LOCK))],
    lock_date: Annotated[date | None, Query()] = None,
    hard_lock_date: Annotated[date | None, Query()] = None,
) -> ApiResponse[PeriodLockPreviewResponse]:
    row = await service.preview(
        tenant.tenant_id,
        lock_date=lock_date,
        hard_lock_date=hard_lock_date,
    )
    return ApiResponse(data=row)


@router.patch("", response_model=ApiResponse[PeriodLockResponse])
async def update_period_lock(
    payload: PeriodLockUpdate,
    tenant: TenantContextDependency,
    service: PeriodLockServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PERIOD_LOCK))],
) -> ApiResponse[PeriodLockResponse]:
    row = await service.apply(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=row, message="Period lock updated successfully")

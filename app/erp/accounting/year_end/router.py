"""Year-end closing routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request

from app.auth.catalog import YEAR_END_MANAGE
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.schemas.response import ApiResponse
from app.erp.accounting.year_end.dependencies import YearEndServiceDependency
from app.erp.accounting.year_end.schemas import (
    YearEndCommitRequest,
    YearEndPreviewResponse,
    YearEndReopenRequest,
    YearEndStateResponse,
)

router = APIRouter(prefix="/year-end", tags=["Year End"])

IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("/state", response_model=ApiResponse[YearEndStateResponse])
async def get_year_end_state(
    tenant: TenantContextDependency,
    service: YearEndServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(YEAR_END_MANAGE))],
    fiscal_year: int = Query(..., ge=1900, le=9999),
) -> ApiResponse[YearEndStateResponse]:
    return ApiResponse(data=await service.get_state(tenant.tenant_id, fiscal_year))


@router.post("/preview", response_model=ApiResponse[YearEndPreviewResponse])
async def preview_year_end(
    payload: YearEndCommitRequest,
    tenant: TenantContextDependency,
    service: YearEndServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(YEAR_END_MANAGE))],
) -> ApiResponse[YearEndPreviewResponse]:
    return ApiResponse(data=await service.preview(tenant.tenant_id, payload.fiscal_year))


@router.post("/commit", response_model=ApiResponse[YearEndStateResponse])
async def commit_year_end(
    payload: YearEndCommitRequest,
    request: Request,
    tenant: TenantContextDependency,
    service: YearEndServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(YEAR_END_MANAGE))],
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[YearEndStateResponse]:
    body = await request.body()
    row = await service.commit(
        tenant.tenant_id,
        payload.fiscal_year,
        actor_user_id=tenant.user_id,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Year-end closing committed")


@router.post("/reopen", response_model=ApiResponse[YearEndStateResponse])
async def reopen_year_end(
    payload: YearEndReopenRequest,
    tenant: TenantContextDependency,
    service: YearEndServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(YEAR_END_MANAGE))],
) -> ApiResponse[YearEndStateResponse]:
    row = await service.reopen(
        tenant.tenant_id,
        payload.fiscal_year,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=row, message="Year-end closing reversed")

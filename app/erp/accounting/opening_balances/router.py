"""Opening-balance go-live routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from app.auth.catalog import OPENING_BALANCE_MANAGE
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.schemas.response import ApiResponse
from app.erp.accounting.opening_balances.dependencies import OpeningBalanceServiceDependency
from app.erp.accounting.opening_balances.schemas import (
    OpeningBalancePayload,
    OpeningBalancePreviewResponse,
    OpeningBalanceStateResponse,
)

router = APIRouter(prefix="/opening-balances", tags=["Opening Balances"])

IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[OpeningBalanceStateResponse])
async def get_opening_balances(
    tenant: TenantContextDependency,
    service: OpeningBalanceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(OPENING_BALANCE_MANAGE))],
) -> ApiResponse[OpeningBalanceStateResponse]:
    return ApiResponse(data=await service.get_state(tenant.tenant_id))


@router.post("/preview", response_model=ApiResponse[OpeningBalancePreviewResponse])
async def preview_opening_balances(
    payload: OpeningBalancePayload,
    tenant: TenantContextDependency,
    service: OpeningBalanceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(OPENING_BALANCE_MANAGE))],
) -> ApiResponse[OpeningBalancePreviewResponse]:
    return ApiResponse(data=await service.preview(tenant.tenant_id, payload))


@router.post("/commit", response_model=ApiResponse[OpeningBalanceStateResponse])
async def commit_opening_balances(
    payload: OpeningBalancePayload,
    request: Request,
    tenant: TenantContextDependency,
    service: OpeningBalanceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(OPENING_BALANCE_MANAGE))],
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[OpeningBalanceStateResponse]:
    body = await request.body()
    row = await service.commit(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Opening balances committed")


@router.post("/reset", response_model=ApiResponse[OpeningBalanceStateResponse])
async def reset_opening_balances(
    tenant: TenantContextDependency,
    service: OpeningBalanceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(OPENING_BALANCE_MANAGE))],
) -> ApiResponse[OpeningBalanceStateResponse]:
    row = await service.reset(tenant.tenant_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Opening balances reset")

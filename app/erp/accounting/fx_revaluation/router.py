"""FX revaluation routes."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from app.auth.catalog import FX_REVALUATION_READ, FX_REVALUATION_REVERSE, FX_REVALUATION_RUN
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.erp.accounting.fx_revaluation.dependencies import FxRevaluationServiceDependency
from app.erp.accounting.fx_revaluation.schemas import (
    FxExposureResponse,
    FxRevaluationReverseRequest,
    FxRevaluationRunRequest,
    FxRevaluationRunResponse,
)

router = APIRouter(prefix="/fx-revaluations", tags=["FX Revaluation"])
IfMatch = Annotated[str | None, Header(alias="If-Match")]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[FxRevaluationRunResponse]])
async def list_fx_revaluations(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: FxRevaluationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(FX_REVALUATION_READ))],
) -> ApiResponse[list[FxRevaluationRunResponse]]:
    rows, total = await service.list(tenant.tenant_id, page=page)
    return paginated_response(rows, params=page, total=total)


@router.get("/exposure", response_model=ApiResponse[FxExposureResponse])
async def fx_exposure(
    tenant: TenantContextDependency,
    service: FxRevaluationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(FX_REVALUATION_READ))],
    as_of: Annotated[date, Query()],
) -> ApiResponse[FxExposureResponse]:
    return ApiResponse(data=await service.exposure(tenant.tenant_id, as_of=as_of))


@router.post("/run", response_model=ApiResponse[FxRevaluationRunResponse])
async def run_fx_revaluation(
    request: Request,
    payload: FxRevaluationRunRequest,
    tenant: TenantContextDependency,
    service: FxRevaluationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(FX_REVALUATION_RUN))],
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[FxRevaluationRunResponse]:
    key = require_idempotency_key(idempotency_key)
    body = await request.body()
    row = await service.run(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
        idempotency_key=key,
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="FX revaluation posted successfully")


@router.get("/{run_id}", response_model=ApiResponse[FxRevaluationRunResponse])
async def get_fx_revaluation(
    run_id: UUID,
    tenant: TenantContextDependency,
    service: FxRevaluationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(FX_REVALUATION_READ))],
) -> ApiResponse[FxRevaluationRunResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, run_id))


@router.post("/{run_id}/reverse", response_model=ApiResponse[FxRevaluationRunResponse])
async def reverse_fx_revaluation(
    request: Request,
    run_id: UUID,
    payload: FxRevaluationReverseRequest,
    tenant: TenantContextDependency,
    service: FxRevaluationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(FX_REVALUATION_REVERSE))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[FxRevaluationRunResponse]:
    expected = require_document_version(if_match=if_match, body_version=payload.version)
    key = require_idempotency_key(idempotency_key)
    body = await request.body()
    row = await service.reverse(
        tenant.tenant_id,
        run_id,
        reversal_date=payload.reversal_date,
        actor_user_id=tenant.user_id,
        expected_version=expected,
        idempotency_key=key,
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="FX revaluation reversed successfully")

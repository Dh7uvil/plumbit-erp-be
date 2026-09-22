"""Cost sheet routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from app.auth.catalog import (
    COST_SHEET_CLOSE,
    COST_SHEET_CONFIRM,
    COST_SHEET_CREATE,
    COST_SHEET_DELETE,
    COST_SHEET_READ,
    COST_SHEET_UPDATE,
    LANDED_COST_CREATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.erp.cost_sheets.dependencies import CostSheetServiceDependency
from app.erp.cost_sheets.schemas import (
    CostSheetCreate,
    CostSheetCreateLandedCostRequest,
    CostSheetFilter,
    CostSheetResponse,
    CostSheetUpdate,
    CostSheetVersionRequest,
)
from app.erp.landed_costs.schemas import LandedCostResponse

router = APIRouter(prefix="/cost-sheets", tags=["Cost Sheets"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[CostSheetResponse]])
async def list_cost_sheets(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: CostSheetServiceDependency,
    filters: Annotated[CostSheetFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(COST_SHEET_READ))],
) -> ApiResponse[list[CostSheetResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        sheet_type=filters.sheet_type.value if filters.sheet_type else None,
        shipment_id=filters.shipment_id,
        purchase_order_id=filters.purchase_order_id,
        supplier_id=filters.supplier_id,
        customer_id=filters.customer_id,
        document_date_from=filters.document_date_from,
        document_date_to=filters.document_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[CostSheetResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_cost_sheet(
    payload: CostSheetCreate,
    tenant: TenantContextDependency,
    service: CostSheetServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(COST_SHEET_CREATE))],
) -> ApiResponse[CostSheetResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Cost sheet created successfully")


@router.get("/{cost_sheet_id}", response_model=ApiResponse[CostSheetResponse])
async def get_cost_sheet(
    cost_sheet_id: UUID,
    tenant: TenantContextDependency,
    service: CostSheetServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(COST_SHEET_READ))],
) -> ApiResponse[CostSheetResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, cost_sheet_id))


@router.patch("/{cost_sheet_id}", response_model=ApiResponse[CostSheetResponse])
async def update_cost_sheet(
    cost_sheet_id: UUID,
    payload: CostSheetUpdate,
    tenant: TenantContextDependency,
    service: CostSheetServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(COST_SHEET_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[CostSheetResponse]:
    version = require_document_version(if_match=if_match, body_version=payload.version)
    row = await service.update(
        tenant.tenant_id,
        cost_sheet_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=version,
    )
    return ApiResponse(data=row, message="Cost sheet updated successfully")


@router.delete("/{cost_sheet_id}", response_model=ApiResponse[CostSheetResponse])
async def delete_cost_sheet(
    cost_sheet_id: UUID,
    tenant: TenantContextDependency,
    service: CostSheetServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(COST_SHEET_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[CostSheetResponse]:
    row = await service.delete(
        tenant.tenant_id,
        cost_sheet_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Cost sheet deleted successfully")


@router.post("/{cost_sheet_id}/confirm", response_model=ApiResponse[CostSheetResponse])
async def confirm_cost_sheet(
    cost_sheet_id: UUID,
    payload: CostSheetVersionRequest,
    tenant: TenantContextDependency,
    service: CostSheetServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(COST_SHEET_CONFIRM))],
    if_match: IfMatch = None,
) -> ApiResponse[CostSheetResponse]:
    expected = require_document_version(if_match=if_match, body_version=payload.version)
    row = await service.confirm(
        tenant.tenant_id,
        cost_sheet_id,
        actor_user_id=tenant.user_id,
        expected_version=expected,
        version=payload.version,
    )
    return ApiResponse(data=row, message="Cost sheet confirmed")


@router.post("/{cost_sheet_id}/close", response_model=ApiResponse[CostSheetResponse])
async def close_cost_sheet(
    cost_sheet_id: UUID,
    payload: CostSheetVersionRequest,
    tenant: TenantContextDependency,
    service: CostSheetServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(COST_SHEET_CLOSE))],
    if_match: IfMatch = None,
) -> ApiResponse[CostSheetResponse]:
    expected = require_document_version(if_match=if_match, body_version=payload.version)
    row = await service.close(
        tenant.tenant_id,
        cost_sheet_id,
        actor_user_id=tenant.user_id,
        expected_version=expected,
        version=payload.version,
    )
    return ApiResponse(data=row, message="Cost sheet closed")


@router.post("/{cost_sheet_id}/reopen", response_model=ApiResponse[CostSheetResponse])
async def reopen_cost_sheet(
    cost_sheet_id: UUID,
    payload: CostSheetVersionRequest,
    tenant: TenantContextDependency,
    service: CostSheetServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(COST_SHEET_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[CostSheetResponse]:
    expected = require_document_version(if_match=if_match, body_version=payload.version)
    row = await service.reopen(
        tenant.tenant_id,
        cost_sheet_id,
        actor_user_id=tenant.user_id,
        expected_version=expected,
        version=payload.version,
    )
    return ApiResponse(data=row, message="Cost sheet reopened")


@router.post("/{cost_sheet_id}/pull-actuals", response_model=ApiResponse[CostSheetResponse])
async def pull_cost_sheet_actuals(
    cost_sheet_id: UUID,
    payload: CostSheetVersionRequest,
    tenant: TenantContextDependency,
    service: CostSheetServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(COST_SHEET_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[CostSheetResponse]:
    expected = require_document_version(if_match=if_match, body_version=payload.version)
    row = await service.pull_actuals(
        tenant.tenant_id,
        cost_sheet_id,
        actor_user_id=tenant.user_id,
        expected_version=expected,
        version=payload.version,
    )
    return ApiResponse(data=row, message="Actuals refreshed from posted documents")


@router.post(
    "/{cost_sheet_id}/create-landed-cost",
    response_model=ApiResponse[LandedCostResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_landed_cost_from_sheet(
    cost_sheet_id: UUID,
    payload: CostSheetCreateLandedCostRequest,
    request: Request,
    tenant: TenantContextDependency,
    service: CostSheetServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LANDED_COST_CREATE))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[LandedCostResponse]:
    body = await request.body()
    expected = require_document_version(if_match=if_match, body_version=payload.version)
    row = await service.create_landed_cost(
        tenant.tenant_id,
        cost_sheet_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=expected,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Landed cost created from cost sheet")

"""Delivery note routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Request, status

from app.auth.catalog import (
    DELIVERY_NOTE_CREATE,
    DELIVERY_NOTE_DELETE,
    DELIVERY_NOTE_POST,
    DELIVERY_NOTE_READ,
    DELIVERY_NOTE_UPDATE,
    PACKAGE_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.inventory_management.delivery_notes.dependencies import DeliveryNoteServiceDependency
from app.inventory_management.delivery_notes.schemas import (
    DeliveryNoteCancelRequest,
    DeliveryNoteCreate,
    DeliveryNoteCreateFromSalesOrder,
    DeliveryNoteFilter,
    DeliveryNoteResponse,
    DeliveryNoteUpdate,
)
from app.inventory_management.packages.dependencies import PackageServiceDependency
from app.inventory_management.packages.schemas import PackageAttachRequest, PackageResponse

router = APIRouter(prefix="/delivery-notes", tags=["Delivery Notes"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[DeliveryNoteResponse]])
async def list_delivery_notes(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: DeliveryNoteServiceDependency,
    filters: Annotated[DeliveryNoteFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(DELIVERY_NOTE_READ))],
) -> ApiResponse[list[DeliveryNoteResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        warehouse_id=filters.warehouse_id,
        customer_id=filters.customer_id,
        sales_order_id=filters.sales_order_id,
        shipment_id=filters.shipment_id,
        unshipped=filters.unshipped,
        product_id=filters.product_id,
        document_date_from=filters.document_date_from,
        document_date_to=filters.document_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "/from-sales-order",
    response_model=ApiResponse[DeliveryNoteResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_delivery_note_from_sales_order(
    payload: DeliveryNoteCreateFromSalesOrder,
    request: Request,
    tenant: TenantContextDependency,
    service: DeliveryNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DELIVERY_NOTE_CREATE))],
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[DeliveryNoteResponse]:
    body = await request.body()
    row = await service.create_from_sales_order(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Delivery note created from sales order")


@router.post(
    "",
    response_model=ApiResponse[DeliveryNoteResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_delivery_note(
    payload: DeliveryNoteCreate,
    tenant: TenantContextDependency,
    service: DeliveryNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DELIVERY_NOTE_CREATE))],
) -> ApiResponse[DeliveryNoteResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Delivery note created successfully")


@router.get("/{note_id}", response_model=ApiResponse[DeliveryNoteResponse])
async def get_delivery_note(
    note_id: UUID,
    tenant: TenantContextDependency,
    service: DeliveryNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DELIVERY_NOTE_READ))],
) -> ApiResponse[DeliveryNoteResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, note_id))


@router.patch("/{note_id}", response_model=ApiResponse[DeliveryNoteResponse])
async def update_delivery_note(
    note_id: UUID,
    payload: DeliveryNoteUpdate,
    tenant: TenantContextDependency,
    service: DeliveryNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DELIVERY_NOTE_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[DeliveryNoteResponse]:
    row = await service.update(
        tenant.tenant_id,
        note_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Delivery note updated successfully")


@router.delete("/{note_id}", response_model=ApiResponse[DeliveryNoteResponse])
async def delete_delivery_note(
    note_id: UUID,
    tenant: TenantContextDependency,
    service: DeliveryNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DELIVERY_NOTE_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[DeliveryNoteResponse]:
    row = await service.delete(
        tenant.tenant_id,
        note_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Delivery note deleted successfully")


@router.post("/{note_id}/post", response_model=ApiResponse[DeliveryNoteResponse])
async def post_delivery_note(
    note_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: DeliveryNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DELIVERY_NOTE_POST))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[DeliveryNoteResponse]:
    body = await request.body()
    row = await service.post(
        tenant.tenant_id,
        note_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Delivery note posted successfully")


@router.post("/{note_id}/cancel", response_model=ApiResponse[DeliveryNoteResponse])
async def cancel_delivery_note(
    note_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: DeliveryNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DELIVERY_NOTE_UPDATE))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
    payload: Annotated[DeliveryNoteCancelRequest | None, Body()] = None,
) -> ApiResponse[DeliveryNoteResponse]:
    body_payload = payload or DeliveryNoteCancelRequest()
    body = await request.body()
    row = await service.cancel(
        tenant.tenant_id,
        note_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(
            if_match=if_match, body_version=body_payload.version
        ),
        reason=body_payload.reason,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Delivery note cancelled")


@router.post("/{note_id}/packages", response_model=ApiResponse[PackageResponse])
async def attach_package_to_delivery_note(
    note_id: UUID,
    payload: PackageAttachRequest,
    tenant: TenantContextDependency,
    packages: PackageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PACKAGE_UPDATE))],
) -> ApiResponse[PackageResponse]:
    row = await packages.attach_to_delivery_note(
        tenant.tenant_id, payload.package_id, note_id, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Package attached to delivery note")


@router.delete("/{note_id}/packages/{package_id}", response_model=ApiResponse[PackageResponse])
async def detach_package_from_delivery_note(
    note_id: UUID,
    package_id: UUID,
    tenant: TenantContextDependency,
    packages: PackageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PACKAGE_UPDATE))],
) -> ApiResponse[PackageResponse]:
    row = await packages.detach_from_delivery_note(
        tenant.tenant_id, package_id, note_id, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Package detached from delivery note")

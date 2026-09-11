"""Shipment routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status

from app.auth.catalog import (
    SHIPMENT_CLOSE,
    SHIPMENT_CREATE,
    SHIPMENT_DELETE,
    SHIPMENT_DISPATCH,
    SHIPMENT_READ,
    SHIPMENT_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.logistics.shipments.dependencies import ShipmentServiceDependency
from app.logistics.shipments.schemas import (
    ShipmentAttachNotesRequest,
    ShipmentCreate,
    ShipmentFilter,
    ShipmentResponse,
    ShipmentTrackingUpdate,
    ShipmentUpdate,
)

router = APIRouter(prefix="/shipments", tags=["Shipments"])

IfMatch = Annotated[str | None, Header()]


@router.get("", response_model=ApiResponse[list[ShipmentResponse]])
async def list_shipments(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: ShipmentServiceDependency,
    filters: Annotated[ShipmentFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(SHIPMENT_READ))],
) -> ApiResponse[list[ShipmentResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        shipment_type=filters.shipment_type.value if filters.shipment_type else None,
        transport_mode=filters.transport_mode.value if filters.transport_mode else None,
    )
    return paginated_response(rows, params=page, total=total)


@router.post("", response_model=ApiResponse[ShipmentResponse], status_code=status.HTTP_201_CREATED)
async def create_shipment(
    payload: ShipmentCreate,
    tenant: TenantContextDependency,
    service: ShipmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SHIPMENT_CREATE))],
) -> ApiResponse[ShipmentResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Shipment created successfully")


@router.get("/{shipment_id}", response_model=ApiResponse[ShipmentResponse])
async def get_shipment(
    shipment_id: UUID,
    tenant: TenantContextDependency,
    service: ShipmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SHIPMENT_READ))],
) -> ApiResponse[ShipmentResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, shipment_id))


@router.patch("/{shipment_id}", response_model=ApiResponse[ShipmentResponse])
async def update_shipment(
    shipment_id: UUID,
    payload: ShipmentUpdate,
    tenant: TenantContextDependency,
    service: ShipmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SHIPMENT_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[ShipmentResponse]:
    row = await service.update(
        tenant.tenant_id,
        shipment_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Shipment updated successfully")


@router.delete("/{shipment_id}", response_model=ApiResponse[ShipmentResponse])
async def delete_shipment(
    shipment_id: UUID,
    tenant: TenantContextDependency,
    service: ShipmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SHIPMENT_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[ShipmentResponse]:
    row = await service.delete(
        tenant.tenant_id,
        shipment_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Shipment deleted successfully")


@router.post("/{shipment_id}/dispatch", response_model=ApiResponse[ShipmentResponse])
async def dispatch_shipment(
    shipment_id: UUID,
    tenant: TenantContextDependency,
    service: ShipmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SHIPMENT_DISPATCH))],
    if_match: IfMatch = None,
) -> ApiResponse[ShipmentResponse]:
    row = await service.dispatch(
        tenant.tenant_id,
        shipment_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Shipment dispatched")


@router.post("/{shipment_id}/arrive", response_model=ApiResponse[ShipmentResponse])
async def arrive_shipment(
    shipment_id: UUID,
    tenant: TenantContextDependency,
    service: ShipmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SHIPMENT_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[ShipmentResponse]:
    row = await service.arrive(
        tenant.tenant_id,
        shipment_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Shipment arrived")


@router.post("/{shipment_id}/close", response_model=ApiResponse[ShipmentResponse])
async def close_shipment(
    shipment_id: UUID,
    tenant: TenantContextDependency,
    service: ShipmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SHIPMENT_CLOSE))],
    if_match: IfMatch = None,
) -> ApiResponse[ShipmentResponse]:
    row = await service.close(
        tenant.tenant_id,
        shipment_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Shipment closed")


@router.post("/{shipment_id}/cancel", response_model=ApiResponse[ShipmentResponse])
async def cancel_shipment(
    shipment_id: UUID,
    tenant: TenantContextDependency,
    service: ShipmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SHIPMENT_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[ShipmentResponse]:
    row = await service.cancel(
        tenant.tenant_id,
        shipment_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Shipment cancelled")


@router.patch("/{shipment_id}/tracking", response_model=ApiResponse[ShipmentResponse])
async def update_shipment_tracking(
    shipment_id: UUID,
    payload: ShipmentTrackingUpdate,
    tenant: TenantContextDependency,
    service: ShipmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SHIPMENT_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[ShipmentResponse]:
    row = await service.update_tracking(
        tenant.tenant_id,
        shipment_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Shipment tracking updated")


@router.post("/{shipment_id}/delivery-notes", response_model=ApiResponse[ShipmentResponse])
async def attach_delivery_notes(
    shipment_id: UUID,
    payload: ShipmentAttachNotesRequest,
    tenant: TenantContextDependency,
    service: ShipmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SHIPMENT_UPDATE))],
) -> ApiResponse[ShipmentResponse]:
    row = await service.attach_delivery_notes(
        tenant.tenant_id,
        shipment_id,
        payload.delivery_note_ids,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=row, message="Delivery notes attached")


@router.delete(
    "/{shipment_id}/delivery-notes/{note_id}",
    response_model=ApiResponse[ShipmentResponse],
)
async def detach_delivery_note(
    shipment_id: UUID,
    note_id: UUID,
    tenant: TenantContextDependency,
    service: ShipmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SHIPMENT_UPDATE))],
) -> ApiResponse[ShipmentResponse]:
    row = await service.detach_delivery_note(
        tenant.tenant_id, shipment_id, note_id, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Delivery note detached")

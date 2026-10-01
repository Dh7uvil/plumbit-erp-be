"""Call routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import CALL_CREATE, CALL_END, CALL_JOIN, CALL_READ
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_any_permission, require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.communication.calls.dependencies import CallServiceDependency
from app.communication.calls.schemas import (
    CallCreate,
    CallFilter,
    CallMediaUpdate,
    CallResponse,
)
from app.communication.shared.feature import require_communication_enabled

router = APIRouter(prefix="/calls", tags=["Communication"])


@router.get("", response_model=ApiResponse[list[CallResponse]])
async def list_calls(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: CallServiceDependency,
    filters: Annotated[CallFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(CALL_READ))],
) -> ApiResponse[list[CallResponse]]:
    require_communication_enabled()
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        conversation_id=filters.conversation_id,
        participant_user_id=tenant.user_id if filters.mine else None,
    )
    return paginated_response(rows, params=page, total=total)


@router.post("", response_model=ApiResponse[CallResponse], status_code=status.HTTP_201_CREATED)
async def create_call(
    payload: CallCreate,
    tenant: TenantContextDependency,
    service: CallServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CALL_CREATE))],
) -> ApiResponse[CallResponse]:
    require_communication_enabled()
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Call created")


@router.get("/{call_id}", response_model=ApiResponse[CallResponse])
async def get_call(
    call_id: UUID,
    tenant: TenantContextDependency,
    service: CallServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CALL_READ))],
) -> ApiResponse[CallResponse]:
    require_communication_enabled()
    row = await service.get(
        tenant.tenant_id, call_id, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row)


@router.post("/{call_id}/accept", response_model=ApiResponse[CallResponse])
async def accept_call(
    call_id: UUID,
    tenant: TenantContextDependency,
    service: CallServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CALL_JOIN))],
) -> ApiResponse[CallResponse]:
    require_communication_enabled()
    row = await service.accept(tenant.tenant_id, call_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row)


@router.post("/{call_id}/reject", response_model=ApiResponse[CallResponse])
async def reject_call(
    call_id: UUID,
    tenant: TenantContextDependency,
    service: CallServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CALL_JOIN))],
) -> ApiResponse[CallResponse]:
    require_communication_enabled()
    row = await service.reject(tenant.tenant_id, call_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row)


@router.post("/{call_id}/join", response_model=ApiResponse[CallResponse])
async def join_call(
    call_id: UUID,
    tenant: TenantContextDependency,
    service: CallServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CALL_JOIN))],
) -> ApiResponse[CallResponse]:
    require_communication_enabled()
    row = await service.join(tenant.tenant_id, call_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row)


@router.post("/{call_id}/leave", response_model=ApiResponse[CallResponse])
async def leave_call(
    call_id: UUID,
    tenant: TenantContextDependency,
    service: CallServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CALL_JOIN))],
) -> ApiResponse[CallResponse]:
    require_communication_enabled()
    row = await service.leave(tenant.tenant_id, call_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row)


@router.post("/{call_id}/end", response_model=ApiResponse[CallResponse])
async def end_call(
    call_id: UUID,
    tenant: TenantContextDependency,
    service: CallServiceDependency,
    _: Annotated[
        CurrentUser,
        Depends(require_any_permission(CALL_END, CALL_CREATE, CALL_JOIN)),
    ],
) -> ApiResponse[CallResponse]:
    require_communication_enabled()
    row = await service.end(tenant.tenant_id, call_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row)


@router.patch("/{call_id}/media", response_model=ApiResponse[CallResponse])
async def update_call_media(
    call_id: UUID,
    payload: CallMediaUpdate,
    tenant: TenantContextDependency,
    service: CallServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CALL_JOIN))],
) -> ApiResponse[CallResponse]:
    require_communication_enabled()
    row = await service.update_media(
        tenant.tenant_id, call_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row)


@router.post("/{call_id}/token/refresh", response_model=ApiResponse[CallResponse])
async def refresh_call_token(
    call_id: UUID,
    tenant: TenantContextDependency,
    service: CallServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CALL_JOIN))],
) -> ApiResponse[CallResponse]:
    require_communication_enabled()
    row = await service.refresh_token(tenant.tenant_id, call_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row)

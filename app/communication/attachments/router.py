"""Chat attachment routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.auth.catalog import COMMUNICATION_ATTACHMENT_READ, MESSAGE_CREATE
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.response import ApiResponse
from app.communication.attachments.dependencies import ChatAttachmentServiceDependency
from app.communication.attachments.schemas import (
    AttachmentCompleteRequest,
    AttachmentDownloadResponse,
    AttachmentPresignRequest,
    AttachmentPresignResponse,
)
from app.communication.messages.schemas import MessageResponse
from app.communication.shared.feature import require_communication_enabled

router = APIRouter(prefix="/attachments", tags=["Communication"])


@router.post(
    "/presign",
    response_model=ApiResponse[AttachmentPresignResponse],
    status_code=status.HTTP_201_CREATED,
)
async def presign_attachment(
    payload: AttachmentPresignRequest,
    tenant: TenantContextDependency,
    service: ChatAttachmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_CREATE))],
) -> ApiResponse[AttachmentPresignResponse]:
    require_communication_enabled()
    row = await service.presign(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Upload URL created")


@router.post(
    "/{attachment_id}/complete",
    response_model=ApiResponse[MessageResponse],
    status_code=status.HTTP_201_CREATED,
)
async def complete_attachment(
    attachment_id: UUID,
    payload: AttachmentCompleteRequest,
    tenant: TenantContextDependency,
    service: ChatAttachmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_CREATE))],
) -> ApiResponse[MessageResponse]:
    require_communication_enabled()
    row = await service.complete(
        tenant.tenant_id,
        attachment_id,
        payload,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=row, message="Attachment message created")


@router.get("/{attachment_id}/content")
async def get_attachment_content(
    attachment_id: UUID,
    tenant: TenantContextDependency,
    service: ChatAttachmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(COMMUNICATION_ATTACHMENT_READ))],
    variant: str = "original",
) -> Response:
    require_communication_enabled()
    body, content_type = await service.get_content(
        tenant.tenant_id,
        attachment_id,
        actor_user_id=tenant.user_id,
        variant=variant,
    )
    return Response(
        content=body,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get(
    "/{attachment_id}",
    response_model=ApiResponse[AttachmentDownloadResponse],
)
async def get_attachment_url(
    attachment_id: UUID,
    tenant: TenantContextDependency,
    service: ChatAttachmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(COMMUNICATION_ATTACHMENT_READ))],
) -> ApiResponse[AttachmentDownloadResponse]:
    require_communication_enabled()
    row = await service.get_download_url(
        tenant.tenant_id,
        attachment_id,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=row)

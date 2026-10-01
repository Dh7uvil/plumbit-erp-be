"""Message routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.auth.catalog import MESSAGE_CREATE, MESSAGE_DELETE, MESSAGE_READ, MESSAGE_UPDATE
from app.common.attachments.dependencies import AttachmentServiceDependency
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.response import ApiResponse
from app.common.utils.files import max_upload_bytes
from app.communication.messages.dependencies import MessageServiceDependency
from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.communication.messages.schemas import (
    DeliveredMarker,
    MessageCreate,
    MessageForwardRequest,
    MessageListParams,
    MessageListResponse,
    MessageResponse,
    MessageUpdate,
    ReactionResponse,
    SavedMessageResponse,
)
from app.communication.shared.feature import require_communication_enabled

router = APIRouter(tags=["Communication"])

_READ_CHUNK_SIZE = 64 * 1024


async def _read_upload(file: UploadFile, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_READ_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValidationError("File exceeds maximum upload size")
        chunks.append(chunk)
    return b"".join(chunks)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=ApiResponse[MessageListResponse],
)
async def list_messages(
    conversation_id: UUID,
    tenant: TenantContextDependency,
    service: MessageServiceDependency,
    params: Annotated[MessageListParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_READ))],
) -> ApiResponse[MessageListResponse]:
    require_communication_enabled()
    result = await service.list(
        tenant.tenant_id,
        conversation_id,
        user_id=tenant.user_id,
        before_seq=params.before_seq,
        after_seq=params.after_seq,
        limit=params.limit,
    )
    return ApiResponse(data=result, meta={"has_more": result.has_more})


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=ApiResponse[MessageResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_message(
    conversation_id: UUID,
    payload: MessageCreate,
    tenant: TenantContextDependency,
    service: MessageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_CREATE))],
) -> ApiResponse[MessageResponse]:
    require_communication_enabled()
    row = await service.create(
        tenant.tenant_id, conversation_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Message created")


@router.post(
    "/conversations/{conversation_id}/messages/attachment",
    response_model=ApiResponse[MessageResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_attachment_message(
    conversation_id: UUID,
    tenant: TenantContextDependency,
    service: MessageServiceDependency,
    attachment_service: AttachmentServiceDependency,
    file: Annotated[UploadFile, File()],
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_CREATE))],
    client_message_id: Annotated[str | None, Form()] = None,
) -> ApiResponse[MessageResponse]:
    require_communication_enabled()
    content = await _read_upload(
        file, max_bytes=max_upload_bytes(get_settings().max_upload_size_mb)
    )
    row = await service.create_with_attachment(
        tenant.tenant_id,
        conversation_id,
        actor_user_id=tenant.user_id,
        filename=file.filename,
        content=content,
        client_message_id=client_message_id,
        attachment_service=attachment_service,
    )
    return ApiResponse(data=row, message="Attachment message created")


@router.post("/conversations/{conversation_id}/delivered", response_model=ApiResponse[None])
async def mark_delivered(
    conversation_id: UUID,
    payload: DeliveredMarker,
    tenant: TenantContextDependency,
    service: MessageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_READ))],
) -> ApiResponse[None]:
    require_communication_enabled()
    await service.mark_delivered(
        tenant.tenant_id,
        conversation_id,
        actor_user_id=tenant.user_id,
        up_to_seq=payload.up_to_seq,
    )
    return ApiResponse(data=None)


@router.patch("/messages/{message_id}", response_model=ApiResponse[MessageResponse])
async def update_message(
    message_id: UUID,
    payload: MessageUpdate,
    tenant: TenantContextDependency,
    service: MessageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_UPDATE))],
) -> ApiResponse[MessageResponse]:
    require_communication_enabled()
    row = await service.update(
        tenant.tenant_id, message_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row)


@router.delete("/messages/{message_id}", response_model=ApiResponse[MessageResponse])
async def delete_message(
    message_id: UUID,
    tenant: TenantContextDependency,
    service: MessageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_DELETE))],
) -> ApiResponse[MessageResponse]:
    require_communication_enabled()
    row = await service.delete(tenant.tenant_id, message_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row)


@router.put(
    "/messages/{message_id}/reactions/{emoji}",
    response_model=ApiResponse[ReactionResponse],
    status_code=status.HTTP_201_CREATED,
)
async def add_reaction(
    message_id: UUID,
    emoji: str,
    tenant: TenantContextDependency,
    service: MessageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_READ))],
) -> ApiResponse[ReactionResponse]:
    require_communication_enabled()
    row = await service.add_reaction(
        tenant.tenant_id, message_id, emoji, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row)


@router.delete("/messages/{message_id}/reactions/{emoji}", response_model=ApiResponse[None])
async def remove_reaction(
    message_id: UUID,
    emoji: str,
    tenant: TenantContextDependency,
    service: MessageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_READ))],
) -> ApiResponse[None]:
    require_communication_enabled()
    await service.remove_reaction(
        tenant.tenant_id, message_id, emoji, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=None)


@router.post(
    "/messages/{message_id}/save",
    response_model=ApiResponse[SavedMessageResponse],
    status_code=status.HTTP_201_CREATED,
)
async def save_message(
    message_id: UUID,
    tenant: TenantContextDependency,
    service: MessageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_READ))],
) -> ApiResponse[SavedMessageResponse]:
    require_communication_enabled()
    row = await service.save_message(
        tenant.tenant_id, message_id, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row)


@router.delete("/messages/{message_id}/save", response_model=ApiResponse[None])
async def unsave_message(
    message_id: UUID,
    tenant: TenantContextDependency,
    service: MessageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_READ))],
) -> ApiResponse[None]:
    require_communication_enabled()
    await service.unsave_message(
        tenant.tenant_id, message_id, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=None)


@router.get("/saved-messages", response_model=ApiResponse[list[MessageResponse]])
async def list_saved_messages(
    tenant: TenantContextDependency,
    service: MessageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_READ))],
) -> ApiResponse[list[MessageResponse]]:
    require_communication_enabled()
    rows = await service.list_saved_messages(
        tenant.tenant_id, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=rows)


@router.post(
    "/messages/{message_id}/forward",
    response_model=ApiResponse[MessageResponse],
    status_code=status.HTTP_201_CREATED,
)
async def forward_message(
    message_id: UUID,
    payload: MessageForwardRequest,
    tenant: TenantContextDependency,
    service: MessageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_CREATE))],
) -> ApiResponse[MessageResponse]:
    require_communication_enabled()
    row = await service.forward_message(
        tenant.tenant_id,
        message_id,
        payload,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=row, message="Message forwarded")

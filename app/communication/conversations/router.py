"""Conversation routes."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import (
    CONVERSATION_CREATE,
    CONVERSATION_DELETE,
    CONVERSATION_READ,
    CONVERSATION_UPDATE,
    MESSAGE_CREATE,
    MESSAGE_READ,
    MESSAGE_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.communication.conversations.dependencies import ConversationServiceDependency
from app.communication.messages.dependencies import MessageServiceDependency
from app.communication.messages.schemas import MessageResponse
from app.communication.conversations.schemas import (
    ConversationCreate,
    ConversationFilter,
    ConversationForContextCreate,
    ConversationResponse,
    ConversationUpdate,
    MySettingsUpdate,
    ParticipantAdd,
    ParticipantResponse,
    ParticipantRoleUpdate,
    ReadMarker,
    TypingEvent,
    UnreadSummaryResponse,
)
from app.communication.shared.feature import require_communication_enabled

router = APIRouter(prefix="/conversations", tags=["Communication"])


@router.get("", response_model=ApiResponse[list[ConversationResponse]])
async def list_conversations(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: ConversationServiceDependency,
    filters: Annotated[ConversationFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(CONVERSATION_READ))],
) -> ApiResponse[list[ConversationResponse]]:
    require_communication_enabled()
    rows, total = await service.list(
        tenant.tenant_id,
        tenant.user_id,
        page=page,
        common_filter=filters,
        kind=filters.kind.value if filters.kind else None,
    )
    return paginated_response(rows, params=page, total=total)


@router.post("", response_model=ApiResponse[ConversationResponse], status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    tenant: TenantContextDependency,
    service: ConversationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONVERSATION_CREATE))],
) -> ApiResponse[ConversationResponse]:
    require_communication_enabled()
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Conversation created")


@router.post(
    "/for-context",
    response_model=ApiResponse[ConversationResponse],
    status_code=status.HTTP_201_CREATED,
)
async def find_or_create_conversation_for_context(
    payload: ConversationForContextCreate,
    tenant: TenantContextDependency,
    service: ConversationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONVERSATION_CREATE))],
) -> ApiResponse[ConversationResponse]:
    require_communication_enabled()
    row = await service.find_or_create_for_context(
        tenant.tenant_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Conversation ready")


@router.get("/unread-summary", response_model=ApiResponse[UnreadSummaryResponse])
async def unread_summary(
    tenant: TenantContextDependency,
    service: ConversationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONVERSATION_READ))],
) -> ApiResponse[UnreadSummaryResponse]:
    require_communication_enabled()
    data = await service.unread_summary(tenant.tenant_id, tenant.user_id)
    return ApiResponse(data=data)


@router.get("/{conversation_id}", response_model=ApiResponse[ConversationResponse])
async def get_conversation(
    conversation_id: UUID,
    tenant: TenantContextDependency,
    service: ConversationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONVERSATION_READ))],
) -> ApiResponse[ConversationResponse]:
    require_communication_enabled()
    row = await service.get(tenant.tenant_id, conversation_id, tenant.user_id)
    return ApiResponse(data=row)


@router.patch("/{conversation_id}", response_model=ApiResponse[ConversationResponse])
async def update_conversation(
    conversation_id: UUID,
    payload: ConversationUpdate,
    tenant: TenantContextDependency,
    service: ConversationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONVERSATION_UPDATE))],
) -> ApiResponse[ConversationResponse]:
    require_communication_enabled()
    row = await service.update(
        tenant.tenant_id, conversation_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row)


@router.delete("/{conversation_id}", response_model=ApiResponse[None])
async def delete_conversation(
    conversation_id: UUID,
    tenant: TenantContextDependency,
    service: ConversationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONVERSATION_DELETE))],
) -> ApiResponse[None]:
    require_communication_enabled()
    await service.delete(tenant.tenant_id, conversation_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=None, message="Conversation deleted")


@router.get("/{conversation_id}/participants", response_model=ApiResponse[list[ParticipantResponse]])
async def list_participants(
    conversation_id: UUID,
    tenant: TenantContextDependency,
    service: ConversationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONVERSATION_READ))],
) -> ApiResponse[list[ParticipantResponse]]:
    require_communication_enabled()
    await service.require_participant(tenant.tenant_id, conversation_id, tenant.user_id)
    rows = await service.participants.list_active(tenant.tenant_id, conversation_id)
    return ApiResponse(data=[ParticipantResponse.model_validate(r) for r in rows])


@router.post(
    "/{conversation_id}/participants",
    response_model=ApiResponse[ParticipantResponse],
    status_code=status.HTTP_201_CREATED,
)
async def add_participant(
    conversation_id: UUID,
    payload: ParticipantAdd,
    tenant: TenantContextDependency,
    service: ConversationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONVERSATION_UPDATE))],
) -> ApiResponse[ParticipantResponse]:
    require_communication_enabled()
    row = await service.add_participant(
        tenant.tenant_id, conversation_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row)


@router.patch(
    "/{conversation_id}/participants/{user_id}",
    response_model=ApiResponse[ParticipantResponse],
)
async def update_participant_role(
    conversation_id: UUID,
    user_id: UUID,
    payload: ParticipantRoleUpdate,
    tenant: TenantContextDependency,
    service: ConversationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONVERSATION_UPDATE))],
) -> ApiResponse[ParticipantResponse]:
    require_communication_enabled()
    row = await service.update_participant_role(
        tenant.tenant_id,
        conversation_id,
        user_id,
        payload,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=row)


@router.delete("/{conversation_id}/participants/{user_id}", response_model=ApiResponse[None])
async def remove_participant(
    conversation_id: UUID,
    user_id: UUID,
    tenant: TenantContextDependency,
    service: ConversationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONVERSATION_UPDATE))],
) -> ApiResponse[None]:
    require_communication_enabled()
    await service.remove_participant(
        tenant.tenant_id, conversation_id, user_id, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=None)


@router.post("/{conversation_id}/leave", response_model=ApiResponse[None])
async def leave_conversation(
    conversation_id: UUID,
    tenant: TenantContextDependency,
    service: ConversationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONVERSATION_READ))],
) -> ApiResponse[None]:
    require_communication_enabled()
    await service.leave(tenant.tenant_id, conversation_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=None)


@router.patch("/{conversation_id}/my-settings", response_model=ApiResponse[ParticipantResponse])
async def update_my_settings(
    conversation_id: UUID,
    payload: MySettingsUpdate,
    tenant: TenantContextDependency,
    service: ConversationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONVERSATION_READ))],
) -> ApiResponse[ParticipantResponse]:
    require_communication_enabled()
    row = await service.update_my_settings(
        tenant.tenant_id, conversation_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row)


@router.post("/{conversation_id}/read", response_model=ApiResponse[None])
async def mark_read(
    conversation_id: UUID,
    payload: ReadMarker,
    tenant: TenantContextDependency,
    service: ConversationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_READ))],
) -> ApiResponse[None]:
    require_communication_enabled()
    await service.mark_read(
        tenant.tenant_id,
        conversation_id,
        actor_user_id=tenant.user_id,
        up_to_seq=payload.up_to_seq,
    )
    return ApiResponse(data=None)


@router.post("/{conversation_id}/typing", response_model=ApiResponse[None])
async def typing(
    conversation_id: UUID,
    payload: TypingEvent,
    tenant: TenantContextDependency,
    service: ConversationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_CREATE))],
) -> ApiResponse[None]:
    require_communication_enabled()
    await service.typing(
        tenant.tenant_id,
        conversation_id,
        actor_user_id=tenant.user_id,
        is_typing=payload.is_typing,
    )
    return ApiResponse(data=None)


@router.get("/{conversation_id}/pins", response_model=ApiResponse[list[MessageResponse]])
async def list_pins(
    conversation_id: UUID,
    tenant: TenantContextDependency,
    message_service: MessageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_READ))],
) -> ApiResponse[list[MessageResponse]]:
    require_communication_enabled()
    rows = await message_service.list_pins(
        tenant.tenant_id, conversation_id, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=rows)


@router.post(
    "/{conversation_id}/pins/{message_id}",
    response_model=ApiResponse[MessageResponse],
    status_code=status.HTTP_201_CREATED,
)
async def pin_message(
    conversation_id: UUID,
    message_id: UUID,
    tenant: TenantContextDependency,
    message_service: MessageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_UPDATE))],
) -> ApiResponse[MessageResponse]:
    require_communication_enabled()
    row = await message_service.pin_message(
        tenant.tenant_id,
        conversation_id,
        message_id,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=row, message="Message pinned")


@router.delete("/{conversation_id}/pins/{message_id}", response_model=ApiResponse[None])
async def unpin_message(
    conversation_id: UUID,
    message_id: UUID,
    tenant: TenantContextDependency,
    message_service: MessageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_UPDATE))],
) -> ApiResponse[None]:
    require_communication_enabled()
    await message_service.unpin_message(
        tenant.tenant_id,
        conversation_id,
        message_id,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=None)


@router.get("/{conversation_id}/attachments", response_model=ApiResponse[list[dict]])
async def list_attachments(
    conversation_id: UUID,
    tenant: TenantContextDependency,
    service: ConversationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_READ))],
    kind: Literal["file", "media"] | None = None,
) -> ApiResponse[list[dict]]:
    require_communication_enabled()
    from sqlalchemy import select

    from app.common.attachments.models import Attachment
    from app.communication.attachments.service import (
        is_media_content_type,
        presign_attachment_preview,
    )
    from app.communication.messages.models import Message
    from app.core.enums import AttachmentEntityType, MessageKind
    from app.integrations.storage.client import get_storage

    await service.require_participant(tenant.tenant_id, conversation_id, tenant.user_id)
    storage = get_storage()
    stmt = (
        select(Attachment, Message)
        .join(Message, Attachment.entity_id == Message.id)
        .where(
            Attachment.tenant_id == tenant.tenant_id,
            Attachment.entity_type == AttachmentEntityType.CHAT_MESSAGE.value,
            Message.conversation_id == conversation_id,
            Message.kind == MessageKind.ATTACHMENT.value,
        )
        .order_by(Message.seq.desc())
    )
    result = await service.session.execute(stmt)
    items: list[dict] = []
    for attachment, message in result.all():
        if kind == "media" and not is_media_content_type(attachment.content_type):
            continue
        if kind == "file" and is_media_content_type(attachment.content_type):
            continue
        thumbnail_url = await presign_attachment_preview(storage, attachment)
        items.append(
            {
                "attachment_id": str(attachment.id),
                "message_id": str(message.id),
                "seq": message.seq,
                "original_filename": attachment.original_filename,
                "content_type": attachment.content_type,
                "size_bytes": attachment.size_bytes,
                "thumbnail_url": thumbnail_url,
            }
        )
    return ApiResponse(data=items)

"""Chat attachment use cases."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.attachments.repository import AttachmentRepository
from app.common.attachments.service import build_thumbnail_key
from app.common.attachments.thumbnails import generate_thumbnail, is_thumbnail_source
from app.common.utils.files import max_upload_bytes, sanitize_filename
from app.communication.attachments.repository import ChatMessageAttachmentRepository
from app.communication.attachments.schemas import (
    AttachmentCompleteRequest,
    AttachmentDownloadResponse,
    AttachmentPresignRequest,
    AttachmentPresignResponse,
)
from app.communication.conversations.service import ConversationService
from app.communication.extended.models import ChatMessageAttachment
from app.communication.messages.models import Message
from app.communication.messages.repository import MessageRepository
from app.communication.messages.schemas import MessageResponse
from app.communication.shared.feature import require_communication_enabled
from app.communication.shared.rate_limit import enforce_upload_rate_limit
from app.communication.shared.signaling_publisher import flush_pending_signaling
from app.core.config import Settings
from app.core.enums import AttachmentEntityType, ChatAttachmentKind, MessageKind
from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.db.session import transaction
from app.common.attachments.models import Attachment
from app.communication.attachments.urls import (
    chat_attachment_content_url,
    use_proxied_attachment_urls,
)
from app.core.config import get_settings
from app.integrations.storage.client import S3Storage, build_object_key


def is_media_content_type(content_type: str) -> bool:
    return content_type.startswith("image/") or content_type.startswith("video/")


async def presign_attachment_preview(
    storage: S3Storage,
    attachment: Attachment,
    *,
    settings: Settings | None = None,
) -> str | None:
    active_settings = settings or get_settings()
    if use_proxied_attachment_urls(active_settings):
        if attachment.thumbnail_storage_key or attachment.content_type.startswith("image/"):
            return chat_attachment_content_url(attachment.id, variant="thumbnail")
        return None
    if attachment.thumbnail_storage_key:
        return await storage.presigned_get_url(key=attachment.thumbnail_storage_key)
    if attachment.content_type.startswith("image/"):
        return await storage.presigned_get_url(key=attachment.storage_key)
    return None


def max_size_mb_for_kind(settings: Settings, kind: ChatAttachmentKind) -> int:
    if kind == ChatAttachmentKind.IMAGE:
        return settings.chat_attachment_image_max_mb
    if kind == ChatAttachmentKind.VIDEO:
        return settings.chat_attachment_video_max_mb
    if kind == ChatAttachmentKind.VOICE:
        return settings.chat_attachment_voice_max_mb
    return settings.chat_attachment_document_max_mb


class ChatAttachmentService:
    def __init__(
        self,
        session: AsyncSession,
        storage: S3Storage,
        settings: Settings,
    ) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings
        self.attachments = AttachmentRepository(session)
        self.chat_attachments = ChatMessageAttachmentRepository(session)
        self.messages = MessageRepository(session)
        self.conversations = ConversationService(session)

    async def presign(
        self,
        tenant_id: UUID,
        payload: AttachmentPresignRequest,
        *,
        actor_user_id: UUID,
    ) -> AttachmentPresignResponse:
        require_communication_enabled()
        enforce_upload_rate_limit(str(actor_user_id))
        await self.conversations.require_participant(
            tenant_id, payload.conversation_id, actor_user_id
        )
        max_mb = max_size_mb_for_kind(self.settings, payload.kind)
        max_bytes = max_upload_bytes(max_mb)
        safe_name = sanitize_filename(payload.filename)
        async with transaction(self.session):
            row = await self.attachments.create(
                tenant_id,
                {
                    "entity_type": AttachmentEntityType.CHAT_MESSAGE.value,
                    "entity_id": payload.conversation_id,
                    "original_filename": safe_name,
                    "content_type": payload.content_type,
                    "size_bytes": 0,
                    "storage_key": "pending",
                    "category": payload.kind.value,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            storage_key = build_object_key(
                tenant_id=tenant_id,
                entity_type=AttachmentEntityType.CHAT_MESSAGE.value,
                entity_id=payload.conversation_id,
                attachment_id=row.id,
                filename=safe_name,
            )
            row.storage_key = storage_key
            await self.session.flush()
            upload_url = await self.storage.presigned_put_url(
                key=storage_key,
                content_type=payload.content_type,
            )
        return AttachmentPresignResponse(
            attachment_id=row.id,
            upload_url=upload_url,
            storage_key=storage_key,
            max_size_bytes=max_bytes,
        )

    async def complete(
        self,
        tenant_id: UUID,
        attachment_id: UUID,
        payload: AttachmentCompleteRequest,
        *,
        actor_user_id: UUID,
    ) -> MessageResponse:
        require_communication_enabled()
        await self.conversations.require_participant(
            tenant_id, payload.conversation_id, actor_user_id
        )
        row = await self.attachments.get(tenant_id, attachment_id)
        if row is None or row.deleted_at is not None:
            raise ResourceNotFoundError("Attachment not found")
        if row.entity_type != AttachmentEntityType.CHAT_MESSAGE.value:
            raise ValidationError("Attachment is not a chat upload")
        if row.entity_id != payload.conversation_id:
            raise ValidationError("Attachment does not belong to this conversation")
        kind = ChatAttachmentKind(row.category or ChatAttachmentKind.DOCUMENT.value)
        max_bytes = max_upload_bytes(max_size_mb_for_kind(self.settings, kind))
        metadata = await self.storage.head_object(key=row.storage_key)
        size_bytes = int(metadata["content_length"])
        if size_bytes <= 0:
            raise ValidationError("Uploaded file is empty")
        if size_bytes > max_bytes:
            raise ValidationError("Uploaded file exceeds the maximum size for this attachment kind")
        content_type = str(metadata["content_type"])
        if client_message_id := payload.client_message_id:
            existing = await self.messages.get_by_client_id(
                tenant_id,
                payload.conversation_id,
                actor_user_id,
                client_message_id,
            )
            if existing:
                from app.communication.messages.service import MessageService

                responses = await MessageService(self.session)._to_responses(
                    tenant_id, [existing]
                )
                return responses[0]
        async with transaction(self.session):
            row.size_bytes = size_bytes
            row.content_type = content_type
            message = await self._create_attachment_message(
                tenant_id,
                payload.conversation_id,
                actor_user_id=actor_user_id,
                filename=row.original_filename,
                client_message_id=payload.client_message_id,
            )
            row.entity_id = message.id
            thumbnail_key: str | None = None
            if is_thumbnail_source(content_type):
                body, _ctype = await self.storage.download(key=row.storage_key)
                generated = generate_thumbnail(body)
                if generated is not None:
                    thumb_bytes, width, height = generated
                    row.image_width = width
                    row.image_height = height
                    row.thumbnail_storage_key = build_thumbnail_key(
                        tenant_id=tenant_id,
                        entity_type=row.entity_type,
                        entity_id=message.id,
                        attachment_id=row.id,
                    )
                    thumbnail_key = row.thumbnail_storage_key
                    await self.storage.upload(
                        key=row.thumbnail_storage_key,
                        body=thumb_bytes,
                        content_type="image/jpeg",
                    )
            await self.chat_attachments.create(
                ChatMessageAttachment(
                    tenant_id=tenant_id,
                    message_id=message.id,
                    attachment_id=row.id,
                    kind=kind.value,
                    duration_ms=payload.duration_ms,
                    width=payload.width or row.image_width,
                    height=payload.height or row.image_height,
                    thumbnail_key=thumbnail_key,
                    scan_status="PENDING",
                )
            )
            attachment_payload = {
                "id": str(row.id),
                "original_filename": row.original_filename,
                "content_type": row.content_type,
                "size_bytes": row.size_bytes,
                "thumbnail_url": None,
            }
            if row.thumbnail_storage_key or row.content_type.startswith("image/"):
                if use_proxied_attachment_urls(self.settings):
                    attachment_payload["thumbnail_url"] = chat_attachment_content_url(
                        row.id,
                        variant="thumbnail",
                    )
                elif row.thumbnail_storage_key:
                    attachment_payload["thumbnail_url"] = await self.storage.presigned_get_url(
                        key=row.thumbnail_storage_key
                    )
            await self._schedule_message_created(
                tenant_id,
                payload.conversation_id,
                actor_user_id=actor_user_id,
                row=message,
                body=row.original_filename,
                client_message_id=payload.client_message_id,
                attachment=attachment_payload,
            )
            from app.communication.messages.service import MessageService

            await MessageService(self.session)._dispatch_message_notifications(
                tenant_id,
                payload.conversation_id,
                actor_user_id=actor_user_id,
                row=message,
                body=row.original_filename,
                mentioned_user_ids=[],
                is_everyone=False,
            )
        await flush_pending_signaling(self.session)
        from app.communication.messages.service import MessageService

        responses = await MessageService(self.session)._to_responses(tenant_id, [message])
        return responses[0]

    async def get_download_url(
        self,
        tenant_id: UUID,
        attachment_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> AttachmentDownloadResponse:
        require_communication_enabled()
        row = await self.attachments.get(tenant_id, attachment_id)
        if row is None or row.deleted_at is not None:
            raise ResourceNotFoundError("Attachment not found")
        if row.entity_type != AttachmentEntityType.CHAT_MESSAGE.value:
            raise ValidationError("Attachment is not a chat upload")
        conversation_id = await self._resolve_conversation_id(tenant_id, row.entity_id)
        await self.conversations.require_participant(
            tenant_id, conversation_id, actor_user_id
        )
        if use_proxied_attachment_urls(self.settings):
            download_url = chat_attachment_content_url(row.id)
        else:
            download_url = await self.storage.presigned_get_url(key=row.storage_key)
        return AttachmentDownloadResponse(
            attachment_id=row.id,
            download_url=download_url,
            content_type=row.content_type,
            size_bytes=row.size_bytes,
            original_filename=row.original_filename,
        )

    async def get_content(
        self,
        tenant_id: UUID,
        attachment_id: UUID,
        *,
        actor_user_id: UUID,
        variant: str = "original",
    ) -> tuple[bytes, str]:
        require_communication_enabled()
        row = await self.attachments.get(tenant_id, attachment_id)
        if row is None or row.deleted_at is not None:
            raise ResourceNotFoundError("Attachment not found")
        if row.entity_type != AttachmentEntityType.CHAT_MESSAGE.value:
            raise ValidationError("Attachment is not a chat upload")
        conversation_id = await self._resolve_conversation_id(tenant_id, row.entity_id)
        await self.conversations.require_participant(
            tenant_id, conversation_id, actor_user_id
        )
        key = row.storage_key
        if variant == "thumbnail" and row.thumbnail_storage_key:
            key = row.thumbnail_storage_key
        return await self.storage.download(key=key)

    async def _resolve_conversation_id(self, tenant_id: UUID, entity_id: UUID) -> UUID:
        message = await self.messages.get(tenant_id, entity_id)
        if message is not None:
            return message.conversation_id
        return entity_id

    async def _create_attachment_message(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        *,
        actor_user_id: UUID,
        filename: str,
        client_message_id: str | None,
    ) -> Message:
        from app.communication.messages.service import MessageService

        return await MessageService(self.session)._create_row(
            tenant_id,
            conversation_id,
            actor_user_id=actor_user_id,
            kind=MessageKind.ATTACHMENT,
            body=filename,
            client_message_id=client_message_id,
        )

    async def _schedule_message_created(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        *,
        actor_user_id: UUID,
        row: Message,
        body: str,
        client_message_id: str | None,
        attachment: dict[str, object],
    ) -> None:
        from app.communication.messages.service import MessageService

        await MessageService(self.session)._schedule_message_created(
            tenant_id,
            conversation_id,
            actor_user_id=actor_user_id,
            row=row,
            body=body,
            kind=MessageKind.ATTACHMENT,
            client_message_id=client_message_id,
            attachment=attachment,
        )

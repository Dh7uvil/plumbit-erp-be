"""Message use cases."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.outbox.service import OutboxService
from app.communication.conversations.repository import ConversationRepository
from app.communication.conversations.service import ConversationService
from app.communication.messages.models import Message
from app.communication.messages.extended_repository import MessageExtendedRepository
from app.communication.messages.mentions import parse_mentions
from app.communication.messages.repository import MessageRepository
from app.communication.messages.schemas import (
    MessageAttachmentResponse,
    MessageCreate,
    MessageForwardRequest,
    MessageListResponse,
    MessageResponse,
    MessageUpdate,
    ReactionResponse,
    SavedMessageResponse,
)
from app.communication.shared.feature import require_communication_enabled
from app.communication.shared.notifications import CommunicationNotificationService
from app.communication.shared.rate_limit import (
    enforce_message_rate_limit,
    enforce_reaction_rate_limit,
)
from app.communication.shared.sanitize import sanitize_message_body
from app.communication.shared.signaling_publisher import (
    build_event,
    flush_pending_signaling,
    schedule_inbox_signaling_events,
    schedule_signaling_event,
)
from app.core.config import get_settings
from app.core.enums import AttachmentEntityType, MessageKind, ParticipantRole
from app.core.exceptions import PermissionDeniedError, ResourceNotFoundError, ValidationError
from app.communication.attachments.service import presign_attachment_preview
from app.db.session import transaction
from app.integrations.storage.client import get_storage

if TYPE_CHECKING:
    from app.common.attachments.models import Attachment
    from app.common.attachments.service import AttachmentService


class MessageService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = MessageRepository(session)
        self.extended = MessageExtendedRepository(session)
        self.conversations = ConversationRepository(session)
        self.conversation_service = ConversationService(session)
        self.notifications = CommunicationNotificationService(session)
        self.outbox = OutboxService(session)

    async def list(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        *,
        user_id: UUID,
        before_seq: int | None = None,
        after_seq: int | None = None,
        limit: int = 50,
    ) -> MessageListResponse:
        require_communication_enabled()
        await self.conversation_service.require_participant(tenant_id, conversation_id, user_id)
        rows = await self.repo.list_keyset(
            tenant_id,
            conversation_id,
            before_seq=before_seq,
            after_seq=after_seq,
            limit=limit,
        )
        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]
        items = await self._to_responses(tenant_id, rows)
        return MessageListResponse(items=items, has_more=has_more)

    async def create(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        payload: MessageCreate,
        *,
        actor_user_id: UUID,
    ) -> MessageResponse:
        require_communication_enabled()
        enforce_message_rate_limit(str(actor_user_id))
        if payload.client_message_id:
            existing = await self.repo.get_by_client_id(
                tenant_id,
                conversation_id,
                actor_user_id,
                payload.client_message_id,
            )
            if existing:
                responses = await self._to_responses(tenant_id, [existing])
                return responses[0]
        body = sanitize_message_body(payload.body)
        mentioned_user_ids, is_everyone = parse_mentions(body)
        async with transaction(self.session):
            row = await self._create_row(
                tenant_id,
                conversation_id,
                actor_user_id=actor_user_id,
                kind=payload.kind,
                body=body,
                client_message_id=payload.client_message_id,
                reply_to_message_id=payload.reply_to_message_id,
            )
            if mentioned_user_ids or is_everyone:
                await self.extended.add_mentions(
                    tenant_id,
                    message_id=row.id,
                    mentioned_user_ids=mentioned_user_ids,
                    is_everyone=is_everyone,
                )
            await self._schedule_message_created(
                tenant_id,
                conversation_id,
                actor_user_id=actor_user_id,
                row=row,
                body=body,
                kind=payload.kind,
                client_message_id=payload.client_message_id,
            )
            await self._dispatch_message_notifications(
                tenant_id,
                conversation_id,
                actor_user_id=actor_user_id,
                row=row,
                body=body,
                mentioned_user_ids=mentioned_user_ids,
                is_everyone=is_everyone,
            )
        await flush_pending_signaling(self.session)
        responses = await self._to_responses(tenant_id, [row])
        return responses[0]

    async def create_with_attachment(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        *,
        actor_user_id: UUID,
        filename: str | None,
        content: bytes,
        client_message_id: str | None,
        attachment_service: AttachmentService,
    ) -> MessageResponse:
        require_communication_enabled()
        enforce_message_rate_limit(str(actor_user_id))
        if client_message_id:
            existing = await self.repo.get_by_client_id(
                tenant_id,
                conversation_id,
                actor_user_id,
                client_message_id,
            )
            if existing:
                responses = await self._to_responses(tenant_id, [existing])
                return responses[0]
        display_name = filename or "attachment"
        async with transaction(self.session):
            row = await self._create_row(
                tenant_id,
                conversation_id,
                actor_user_id=actor_user_id,
                kind=MessageKind.ATTACHMENT,
                body=display_name,
                client_message_id=client_message_id,
            )
            attachment = await attachment_service.create(
                tenant_id,
                entity_type=AttachmentEntityType.CHAT_MESSAGE,
                entity_id=row.id,
                filename=filename,
                content=content,
                actor_user_id=actor_user_id,
            )
            attachment_payload = {
                "id": str(attachment.id),
                "original_filename": attachment.original_filename,
                "content_type": attachment.content_type,
                "size_bytes": attachment.size_bytes,
                "thumbnail_url": attachment.thumbnail_url,
            }
            await self._schedule_message_created(
                tenant_id,
                conversation_id,
                actor_user_id=actor_user_id,
                row=row,
                body=display_name,
                kind=MessageKind.ATTACHMENT,
                client_message_id=client_message_id,
                attachment=attachment_payload,
            )
            await self._dispatch_message_notifications(
                tenant_id,
                conversation_id,
                actor_user_id=actor_user_id,
                row=row,
                body=display_name,
                mentioned_user_ids=[],
                is_everyone=False,
            )
        await flush_pending_signaling(self.session)
        responses = await self._to_responses(tenant_id, [row])
        return responses[0]

    async def update(
        self,
        tenant_id: UUID,
        message_id: UUID,
        payload: MessageUpdate,
        *,
        actor_user_id: UUID,
    ) -> MessageResponse:
        require_communication_enabled()
        settings = get_settings()
        async with transaction(self.session):
            row = await self.repo.get(tenant_id, message_id)
            if row is None:
                raise ResourceNotFoundError("Message not found")
            await self.conversation_service.require_participant(
                tenant_id, row.conversation_id, actor_user_id
            )
            if row.sender_id != actor_user_id:
                raise PermissionDeniedError()
            if row.deleted_at is not None:
                raise ValidationError("Message is deleted")
            from app.common.utils.datetime import utcnow

            age = (utcnow() - row.created_at).total_seconds()
            if age > settings.chat_message_edit_window_seconds:
                raise ValidationError("Edit window has expired")
            body = sanitize_message_body(payload.body)
            row = await self.repo.update(
                row, {"body": body, "edited_at": utcnow()}
            )
            schedule_signaling_event(
                self.session,
                build_event(
                    event_type="message.updated",
                    tenant_id=tenant_id,
                    actor_id=actor_user_id,
                    conversation_id=row.conversation_id,
                    seq=row.seq,
                    data={"id": str(row.id), "body": body},
                ),
            )
        await flush_pending_signaling(self.session)
        responses = await self._to_responses(tenant_id, [row])
        return responses[0]

    async def delete(
        self, tenant_id: UUID, message_id: UUID, *, actor_user_id: UUID
    ) -> MessageResponse:
        require_communication_enabled()
        async with transaction(self.session):
            row = await self.repo.get(tenant_id, message_id)
            if row is None:
                raise ResourceNotFoundError("Message not found")
            part = await self.conversation_service.require_participant(
                tenant_id, row.conversation_id, actor_user_id
            )
            if row.sender_id != actor_user_id and part.role not in (
                ParticipantRole.OWNER.value,
                ParticipantRole.ADMIN.value,
            ):
                raise PermissionDeniedError()
            from app.common.utils.datetime import utcnow

            row = await self.repo.update(
                row,
                {"deleted_at": utcnow(), "deleted_by": actor_user_id, "body": None},
            )
            schedule_signaling_event(
                self.session,
                build_event(
                    event_type="message.deleted",
                    tenant_id=tenant_id,
                    actor_id=actor_user_id,
                    conversation_id=row.conversation_id,
                    seq=row.seq,
                    data={"id": str(row.id)},
                ),
            )
        await flush_pending_signaling(self.session)
        responses = await self._to_responses(tenant_id, [row])
        return responses[0]

    async def get_for_attachment_probe(
        self, tenant_id: UUID, message_id: UUID
    ) -> Message | None:
        return await self.repo.get(tenant_id, message_id)

    async def post_call_event_message(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        *,
        call_id: UUID,
        call_kind: str,
        duration_seconds: int | None,
        missed: bool,
        end_reason: str | None,
        actor_user_id: UUID | None = None,
    ) -> MessageResponse:
        require_communication_enabled()
        conv = await self.conversations.lock_for_update(tenant_id, conversation_id)
        if conv is None:
            raise ResourceNotFoundError("Conversation not found")
        existing_event = await self.repo.get_call_event_message(
            tenant_id, conversation_id, call_id
        )
        if existing_event is not None:
            responses = await self._to_responses(tenant_id, [existing_event])
            return responses[0]
        seq = conv.message_seq + 1
        system_payload = {
            "call_id": str(call_id),
            "kind": call_kind,
            "duration_seconds": duration_seconds,
            "missed": missed,
            "end_reason": end_reason,
        }
        row = await self.repo.create(
            Message(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                seq=seq,
                sender_id=None,
                kind=MessageKind.CALL_EVENT.value,
                body=None,
                system_payload=system_payload,
            )
        )
        from app.common.utils.datetime import utcnow

        await self.conversations.update(
            tenant_id,
            conversation_id,
            {
                "message_seq": seq,
                "last_message_id": row.id,
                "last_message_at": utcnow(),
            },
        )
        schedule_signaling_event(
            self.session,
            build_event(
                event_type="message.created",
                tenant_id=tenant_id,
                actor_id=actor_user_id,
                conversation_id=conversation_id,
                seq=seq,
                data={
                    "id": str(row.id),
                    "kind": MessageKind.CALL_EVENT.value,
                    "system_payload": system_payload,
                },
            ),
        )
        participants = await self.conversation_service.participants.list_active(
            tenant_id, conversation_id
        )
        for participant in participants:
            schedule_signaling_event(
                self.session,
                build_event(
                    event_type="message.created",
                    tenant_id=tenant_id,
                    actor_id=actor_user_id,
                    conversation_id=conversation_id,
                    seq=seq,
                    data={
                        "id": str(row.id),
                        "kind": MessageKind.CALL_EVENT.value,
                        "system_payload": system_payload,
                        "target_user_id": str(participant.user_id),
                    },
                ),
            )
        responses = await self._to_responses(tenant_id, [row])
        return responses[0]

    async def mark_delivered(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        *,
        actor_user_id: UUID,
        up_to_seq: int,
    ) -> None:
        require_communication_enabled()
        async with transaction(self.session):
            conv, part = await self.conversation_service._require_member(
                tenant_id, conversation_id, actor_user_id
            )
            new_seq = min(up_to_seq, conv.message_seq)
            if new_seq > part.last_delivered_seq:
                await self.conversation_service.participants.update_participant(
                    part, {"last_delivered_seq": new_seq}
                )
                participants = await self.conversation_service.participants.list_active(
                    tenant_id, conversation_id
                )
                schedule_inbox_signaling_events(
                    self.session,
                    build_event(
                        event_type="message.delivered",
                        tenant_id=tenant_id,
                        actor_id=actor_user_id,
                        conversation_id=conversation_id,
                        seq=new_seq,
                        data={
                            "user_id": str(actor_user_id),
                            "up_to_seq": new_seq,
                        },
                    ),
                    participant_user_ids=[row.user_id for row in participants],
                    actor_user_id=actor_user_id,
                )
        await flush_pending_signaling(self.session)

    async def add_reaction(
        self,
        tenant_id: UUID,
        message_id: UUID,
        emoji: str,
        *,
        actor_user_id: UUID,
    ) -> ReactionResponse:
        require_communication_enabled()
        enforce_reaction_rate_limit(str(actor_user_id))
        async with transaction(self.session):
            row = await self.repo.get(tenant_id, message_id)
            if row is None:
                raise ResourceNotFoundError("Message not found")
            await self.conversation_service.require_participant(
                tenant_id, row.conversation_id, actor_user_id
            )
            reaction = await self.extended.add_reaction(
                tenant_id,
                message_id=message_id,
                user_id=actor_user_id,
                emoji=emoji,
            )
            schedule_signaling_event(
                self.session,
                build_event(
                    event_type="message.reaction_changed",
                    tenant_id=tenant_id,
                    actor_id=actor_user_id,
                    conversation_id=row.conversation_id,
                    seq=row.seq,
                    data={
                        "message_id": str(message_id),
                        "emoji": emoji,
                        "user_id": str(actor_user_id),
                        "action": "added",
                    },
                ),
            )
        await flush_pending_signaling(self.session)
        return ReactionResponse.model_validate(reaction)

    async def remove_reaction(
        self,
        tenant_id: UUID,
        message_id: UUID,
        emoji: str,
        *,
        actor_user_id: UUID,
    ) -> None:
        require_communication_enabled()
        async with transaction(self.session):
            row = await self.repo.get(tenant_id, message_id)
            if row is None:
                raise ResourceNotFoundError("Message not found")
            await self.conversation_service.require_participant(
                tenant_id, row.conversation_id, actor_user_id
            )
            await self.extended.remove_reaction(
                tenant_id,
                message_id=message_id,
                user_id=actor_user_id,
                emoji=emoji,
            )
            schedule_signaling_event(
                self.session,
                build_event(
                    event_type="message.reaction_changed",
                    tenant_id=tenant_id,
                    actor_id=actor_user_id,
                    conversation_id=row.conversation_id,
                    seq=row.seq,
                    data={
                        "message_id": str(message_id),
                        "emoji": emoji,
                        "user_id": str(actor_user_id),
                        "action": "removed",
                    },
                ),
            )
        await flush_pending_signaling(self.session)

    async def pin_message(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> MessageResponse:
        require_communication_enabled()
        async with transaction(self.session):
            await self.conversation_service.require_participant(
                tenant_id, conversation_id, actor_user_id
            )
            row = await self.repo.get(tenant_id, message_id)
            if row is None or row.conversation_id != conversation_id:
                raise ResourceNotFoundError("Message not found")
            await self.extended.pin_message(
                tenant_id,
                conversation_id=conversation_id,
                message_id=message_id,
                pinned_by=actor_user_id,
            )
            schedule_signaling_event(
                self.session,
                build_event(
                    event_type="message.pinned",
                    tenant_id=tenant_id,
                    actor_id=actor_user_id,
                    conversation_id=conversation_id,
                    seq=row.seq,
                    data={
                        "message_id": str(message_id),
                        "pinned": True,
                    },
                ),
            )
        await flush_pending_signaling(self.session)
        responses = await self._to_responses(tenant_id, [row])
        return responses[0]

    async def unpin_message(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> None:
        require_communication_enabled()
        async with transaction(self.session):
            await self.conversation_service.require_participant(
                tenant_id, conversation_id, actor_user_id
            )
            await self.extended.unpin_message(
                tenant_id,
                conversation_id=conversation_id,
                message_id=message_id,
            )

    async def list_pins(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> list[MessageResponse]:
        require_communication_enabled()
        await self.conversation_service.require_participant(
            tenant_id, conversation_id, actor_user_id
        )
        rows = await self.extended.list_pins(tenant_id, conversation_id)
        return await self._to_responses(tenant_id, rows)

    async def save_message(
        self,
        tenant_id: UUID,
        message_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> SavedMessageResponse:
        require_communication_enabled()
        async with transaction(self.session):
            row = await self.repo.get(tenant_id, message_id)
            if row is None:
                raise ResourceNotFoundError("Message not found")
            await self.conversation_service.require_participant(
                tenant_id, row.conversation_id, actor_user_id
            )
            saved = await self.extended.save_message(
                tenant_id,
                user_id=actor_user_id,
                message_id=message_id,
            )
        responses = await self._to_responses(tenant_id, [row])
        return SavedMessageResponse(message=responses[0], saved_at=saved.saved_at)

    async def unsave_message(
        self,
        tenant_id: UUID,
        message_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> None:
        require_communication_enabled()
        async with transaction(self.session):
            row = await self.repo.get(tenant_id, message_id)
            if row is None:
                raise ResourceNotFoundError("Message not found")
            await self.conversation_service.require_participant(
                tenant_id, row.conversation_id, actor_user_id
            )
            await self.extended.unsave_message(
                tenant_id,
                user_id=actor_user_id,
                message_id=message_id,
            )

    async def list_saved_messages(
        self,
        tenant_id: UUID,
        *,
        actor_user_id: UUID,
        limit: int = 50,
    ) -> list[MessageResponse]:
        require_communication_enabled()
        rows = await self.extended.list_saved_messages(
            tenant_id, actor_user_id, limit=limit
        )
        return await self._to_responses(tenant_id, rows)

    async def forward_message(
        self,
        tenant_id: UUID,
        message_id: UUID,
        payload: MessageForwardRequest,
        *,
        actor_user_id: UUID,
    ) -> MessageResponse:
        require_communication_enabled()
        enforce_message_rate_limit(str(actor_user_id))
        if payload.client_message_id:
            existing = await self.repo.get_by_client_id(
                tenant_id,
                payload.conversation_id,
                actor_user_id,
                payload.client_message_id,
            )
            if existing:
                responses = await self._to_responses(tenant_id, [existing])
                return responses[0]
        source = await self.repo.get(tenant_id, message_id)
        if source is None or source.deleted_at is not None:
            raise ResourceNotFoundError("Message not found")
        await self.conversation_service.require_participant(
            tenant_id, source.conversation_id, actor_user_id
        )
        body = source.body or ""
        if body:
            body = sanitize_message_body(body)
        async with transaction(self.session):
            row = await self._create_row(
                tenant_id,
                payload.conversation_id,
                actor_user_id=actor_user_id,
                kind=MessageKind(source.kind),
                body=body,
                client_message_id=payload.client_message_id,
                reply_to_message_id=None,
            )
            row.forwarded_from_message_id = source.id
            await self.session.flush()
            await self._schedule_message_created(
                tenant_id,
                payload.conversation_id,
                actor_user_id=actor_user_id,
                row=row,
                body=body,
                kind=MessageKind(source.kind),
                client_message_id=payload.client_message_id,
            )
            await self._dispatch_message_notifications(
                tenant_id,
                payload.conversation_id,
                actor_user_id=actor_user_id,
                row=row,
                body=body,
                mentioned_user_ids=[],
                is_everyone=False,
            )
        await flush_pending_signaling(self.session)
        responses = await self._to_responses(tenant_id, [row])
        return responses[0]

    async def _create_row(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        *,
        actor_user_id: UUID,
        kind: MessageKind,
        body: str,
        client_message_id: str | None,
        reply_to_message_id: UUID | None = None,
    ) -> Message:
        part = await self.conversation_service.require_participant(
            tenant_id, conversation_id, actor_user_id
        )
        conv = await self.conversations.lock_for_update(tenant_id, conversation_id)
        if conv is None:
            raise ResourceNotFoundError("Conversation not found")
        if conv.is_locked:
            raise ValidationError("Conversation is locked")
        if conv.only_admins_can_post and part.role == ParticipantRole.MEMBER.value:
            raise PermissionDeniedError()
        seq = conv.message_seq + 1
        try:
            async with self.session.begin_nested():
                row = await self.repo.create(
                    Message(
                        tenant_id=tenant_id,
                        conversation_id=conversation_id,
                        seq=seq,
                        sender_id=actor_user_id,
                        kind=kind.value,
                        body=body,
                        reply_to_message_id=reply_to_message_id,
                        client_message_id=client_message_id,
                    )
                )
        except IntegrityError:
            if client_message_id:
                existing = await self.repo.get_by_client_id(
                    tenant_id,
                    conversation_id,
                    actor_user_id,
                    client_message_id,
                )
                if existing is not None:
                    return existing
            raise
        from app.common.utils.datetime import utcnow

        await self.conversations.update(
            tenant_id,
            conversation_id,
            {
                "message_seq": seq,
                "last_message_id": row.id,
                "last_message_at": utcnow(),
            },
        )
        await self.conversation_service.participants.update_participant(
            part,
            {"last_read_seq": seq, "last_delivered_seq": seq},
        )
        return row

    async def _schedule_message_created(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        *,
        actor_user_id: UUID,
        row: Message,
        body: str,
        kind: MessageKind,
        client_message_id: str | None,
        attachment: dict[str, object] | None = None,
    ) -> None:
        data: dict[str, object] = {
            "id": str(row.id),
            "body": body,
            "kind": kind.value,
            "client_message_id": client_message_id,
            "sender_id": str(actor_user_id),
        }
        if attachment is not None:
            data["attachment"] = attachment
        schedule_signaling_event(
            self.session,
            build_event(
                event_type="message.created",
                tenant_id=tenant_id,
                actor_id=actor_user_id,
                conversation_id=conversation_id,
                seq=row.seq,
                data=data,
            ),
        )
        participants = await self.conversation_service.participants.list_active(
            tenant_id, conversation_id
        )
        for participant in participants:
            if participant.user_id == actor_user_id:
                continue
            schedule_signaling_event(
                self.session,
                build_event(
                    event_type="message.created",
                    tenant_id=tenant_id,
                    actor_id=actor_user_id,
                    conversation_id=conversation_id,
                    seq=row.seq,
                    data={**data, "target_user_id": str(participant.user_id)},
                ),
            )

    async def _dispatch_message_notifications(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        *,
        actor_user_id: UUID,
        row: Message,
        body: str,
        mentioned_user_ids: list[UUID],
        is_everyone: bool,
    ) -> None:
        conv = await self.conversations.get(tenant_id, conversation_id)
        if conv is None:
            return
        sender_name = await self._user_display_name(tenant_id, actor_user_id)
        preview = body[:200]
        participants = await self.conversation_service.participants.list_active(
            tenant_id, conversation_id
        )
        mention_targets = set(mentioned_user_ids)
        if is_everyone:
            mention_targets = {part.user_id for part in participants if part.user_id != actor_user_id}
        for participant in participants:
            if participant.user_id == actor_user_id:
                continue
            if participant.user_id in mention_targets:
                await self.notifications.notify_mention(
                    tenant_id,
                    conversation=conv,
                    recipient=participant,
                    sender_name=sender_name,
                    preview=preview,
                    message_id=row.id,
                )
            else:
                await self.notifications.notify_new_message(
                    tenant_id,
                    conversation=conv,
                    recipient=participant,
                    sender_name=sender_name,
                    preview=preview,
                    message_id=row.id,
                )

    async def _user_display_name(self, tenant_id: UUID, user_id: UUID) -> str:
        from sqlalchemy import select

        from app.auth.models import User

        stmt = select(User.name).where(User.tenant_id == tenant_id, User.id == user_id)
        result = await self.session.execute(stmt)
        name = result.scalar_one_or_none()
        return name or "Someone"

    async def _attachment_response(self, attachment: Attachment) -> MessageAttachmentResponse:
        storage = get_storage()
        thumbnail_url = await presign_attachment_preview(storage, attachment)
        return MessageAttachmentResponse(
            id=attachment.id,
            original_filename=attachment.original_filename,
            content_type=attachment.content_type,
            size_bytes=attachment.size_bytes,
            thumbnail_url=thumbnail_url,
        )

    async def _to_responses(
        self, tenant_id: UUID, rows: list[Message]
    ) -> list[MessageResponse]:
        attachment_ids = [row.id for row in rows if row.kind == MessageKind.ATTACHMENT.value]
        attachments = await self.repo.attachments_for_messages(tenant_id, attachment_ids)
        responses: list[MessageResponse] = []
        for row in rows:
            response = MessageResponse.model_validate(row)
            attachment = attachments.get(row.id)
            if attachment is not None:
                response.attachment = await self._attachment_response(attachment)
            responses.append(response)
        return responses

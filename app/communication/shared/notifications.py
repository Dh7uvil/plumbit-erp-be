"""In-app notifications for communication events."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.notifications.service import NotificationService
from app.common.utils.datetime import utcnow
from app.communication.conversations.models import Conversation, ConversationParticipant
from app.communication.extended.models import ChatNotificationSettings
from app.communication.settings.repository import ChatNotificationSettingsRepository
from app.core.enums import ConversationKind


class CommunicationNotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.notifications = NotificationService(session)
        self.settings_repo = ChatNotificationSettingsRepository(session)

    async def notify_new_message(
        self,
        tenant_id: UUID,
        *,
        conversation: Conversation,
        recipient: ConversationParticipant,
        sender_name: str,
        preview: str,
        message_id: UUID,
    ) -> None:
        if not await self._should_notify_message(
            tenant_id,
            recipient,
            conversation,
            mention=False,
        ):
            return
        title = conversation.name or sender_name
        await self.notifications.create(
            tenant_id,
            recipient.user_id,
            event="communication.message.new",
            entity_type="message",
            entity_id=message_id,
            title=title,
            body=preview,
        )

    async def notify_mention(
        self,
        tenant_id: UUID,
        *,
        conversation: Conversation,
        recipient: ConversationParticipant,
        sender_name: str,
        preview: str,
        message_id: UUID,
    ) -> None:
        if not await self._should_notify_message(
            tenant_id,
            recipient,
            conversation,
            mention=True,
        ):
            return
        title = f"{sender_name} mentioned you"
        if conversation.kind == ConversationKind.GROUP.value and conversation.name:
            title = f"{sender_name} mentioned you in {conversation.name}"
        await self.notifications.create(
            tenant_id,
            recipient.user_id,
            event="communication.message.mention",
            entity_type="message",
            entity_id=message_id,
            title=title,
            body=preview,
        )

    async def notify_group_invite(
        self,
        tenant_id: UUID,
        *,
        user_id: UUID,
        conversation_id: UUID,
        conversation_name: str,
        inviter_name: str,
    ) -> None:
        if not await self._should_notify_group(tenant_id, user_id):
            return
        await self.notifications.create(
            tenant_id,
            user_id,
            event="communication.group.invite",
            entity_type="conversation",
            entity_id=conversation_id,
            title="Added to a group",
            body=f"{inviter_name} added you to {conversation_name}",
        )

    async def notify_incoming_call(
        self,
        tenant_id: UUID,
        *,
        user_id: UUID,
        call_id: UUID,
        caller_name: str,
        is_video: bool,
    ) -> None:
        if not await self._should_notify_call(tenant_id, user_id):
            return
        kind = "Video" if is_video else "Voice"
        await self.notifications.create(
            tenant_id,
            user_id,
            event="communication.call.incoming",
            entity_type="call",
            entity_id=call_id,
            title=f"Incoming {kind.lower()} call",
            body=f"{caller_name} is calling you",
        )

    async def notify_missed_call(
        self,
        tenant_id: UUID,
        *,
        user_id: UUID,
        call_id: UUID,
        caller_name: str,
        is_video: bool,
    ) -> None:
        if not await self._should_notify_call(tenant_id, user_id):
            return
        kind = "Video" if is_video else "Voice"
        await self.notifications.create(
            tenant_id,
            user_id,
            event="communication.call.missed",
            entity_type="call",
            entity_id=call_id,
            title=f"Missed {kind.lower()} call",
            body=f"Missed call from {caller_name}",
        )

    async def _should_notify_message(
        self,
        tenant_id: UUID,
        participant: ConversationParticipant,
        conversation: Conversation,
        *,
        mention: bool,
    ) -> bool:
        if self._is_participant_muted(participant):
            return False
        if participant.notification_level == "NONE":
            return False
        if participant.notification_level == "MENTIONS" and not mention:
            return False
        settings = await self._get_settings(tenant_id, participant.user_id)
        if conversation.kind == ConversationKind.GROUP.value:
            return settings.group_notifications
        return settings.message_notifications

    async def _should_notify_group(self, tenant_id: UUID, user_id: UUID) -> bool:
        settings = await self._get_settings(tenant_id, user_id)
        return settings.group_notifications

    async def _should_notify_call(self, tenant_id: UUID, user_id: UUID) -> bool:
        settings = await self._get_settings(tenant_id, user_id)
        return settings.call_notifications

    async def _get_settings(
        self, tenant_id: UUID, user_id: UUID
    ) -> ChatNotificationSettings:
        row = await self.settings_repo.get_or_create(tenant_id, user_id)
        return row

    @staticmethod
    def _is_participant_muted(participant: ConversationParticipant) -> bool:
        if participant.is_muted:
            return True
        if participant.muted_until is not None and participant.muted_until > utcnow():
            return True
        return False

"""Extended message feature repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.communication.extended.models import (
    ChatMessageMention,
    ChatMessageReaction,
    ChatPinnedMessage,
    ChatSavedMessage,
)
from app.communication.messages.models import Message


class MessageExtendedRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_reaction(
        self,
        tenant_id: UUID,
        *,
        message_id: UUID,
        user_id: UUID,
        emoji: str,
    ) -> ChatMessageReaction:
        row = ChatMessageReaction(
            tenant_id=tenant_id,
            message_id=message_id,
            user_id=user_id,
            emoji=emoji,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def remove_reaction(
        self,
        tenant_id: UUID,
        *,
        message_id: UUID,
        user_id: UUID,
        emoji: str,
    ) -> None:
        stmt = delete(ChatMessageReaction).where(
            ChatMessageReaction.tenant_id == tenant_id,
            ChatMessageReaction.message_id == message_id,
            ChatMessageReaction.user_id == user_id,
            ChatMessageReaction.emoji == emoji,
        )
        await self.session.execute(stmt)

    async def list_reactions(
        self, tenant_id: UUID, message_id: UUID
    ) -> list[ChatMessageReaction]:
        stmt = select(ChatMessageReaction).where(
            ChatMessageReaction.tenant_id == tenant_id,
            ChatMessageReaction.message_id == message_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add_mentions(
        self,
        tenant_id: UUID,
        *,
        message_id: UUID,
        mentioned_user_ids: list[UUID],
        is_everyone: bool,
    ) -> None:
        if is_everyone:
            self.session.add(
                ChatMessageMention(
                    tenant_id=tenant_id,
                    message_id=message_id,
                    mentioned_user_id=None,
                    is_everyone=True,
                )
            )
        for user_id in mentioned_user_ids:
            self.session.add(
                ChatMessageMention(
                    tenant_id=tenant_id,
                    message_id=message_id,
                    mentioned_user_id=user_id,
                    is_everyone=False,
                )
            )
        await self.session.flush()

    async def list_mentions(
        self, tenant_id: UUID, message_id: UUID
    ) -> list[ChatMessageMention]:
        stmt = select(ChatMessageMention).where(
            ChatMessageMention.tenant_id == tenant_id,
            ChatMessageMention.message_id == message_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def pin_message(
        self,
        tenant_id: UUID,
        *,
        conversation_id: UUID,
        message_id: UUID,
        pinned_by: UUID,
    ) -> ChatPinnedMessage:
        row = ChatPinnedMessage(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message_id=message_id,
            pinned_by=pinned_by,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def unpin_message(
        self,
        tenant_id: UUID,
        *,
        conversation_id: UUID,
        message_id: UUID,
    ) -> None:
        stmt = delete(ChatPinnedMessage).where(
            ChatPinnedMessage.tenant_id == tenant_id,
            ChatPinnedMessage.conversation_id == conversation_id,
            ChatPinnedMessage.message_id == message_id,
        )
        await self.session.execute(stmt)

    async def list_pins(self, tenant_id: UUID, conversation_id: UUID) -> list[Message]:
        stmt = (
            select(Message)
            .join(
                ChatPinnedMessage,
                ChatPinnedMessage.message_id == Message.id,
            )
            .where(
                ChatPinnedMessage.tenant_id == tenant_id,
                ChatPinnedMessage.conversation_id == conversation_id,
            )
            .order_by(ChatPinnedMessage.pinned_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def save_message(
        self,
        tenant_id: UUID,
        *,
        user_id: UUID,
        message_id: UUID,
    ) -> ChatSavedMessage:
        row = ChatSavedMessage(
            tenant_id=tenant_id,
            user_id=user_id,
            message_id=message_id,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def unsave_message(
        self,
        tenant_id: UUID,
        *,
        user_id: UUID,
        message_id: UUID,
    ) -> None:
        stmt = delete(ChatSavedMessage).where(
            ChatSavedMessage.tenant_id == tenant_id,
            ChatSavedMessage.user_id == user_id,
            ChatSavedMessage.message_id == message_id,
        )
        await self.session.execute(stmt)

    async def list_saved_messages(
        self, tenant_id: UUID, user_id: UUID, *, limit: int = 50
    ) -> list[Message]:
        stmt = (
            select(Message)
            .join(ChatSavedMessage, ChatSavedMessage.message_id == Message.id)
            .where(
                ChatSavedMessage.tenant_id == tenant_id,
                ChatSavedMessage.user_id == user_id,
            )
            .order_by(ChatSavedMessage.saved_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

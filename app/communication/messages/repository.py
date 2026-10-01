"""Message repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.attachments.models import Attachment
from app.communication.messages.models import Message
from app.core.enums import AttachmentEntityType, MessageKind


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_many(
        self, tenant_id: UUID, message_ids: list[UUID]
    ) -> dict[UUID, Message]:
        if not message_ids:
            return {}
        stmt = select(Message).where(
            Message.tenant_id == tenant_id,
            Message.id.in_(message_ids),
        )
        result = await self.session.execute(stmt)
        return {row.id: row for row in result.scalars().all()}

    async def get(self, tenant_id: UUID, message_id: UUID) -> Message | None:
        stmt = select(Message).where(
            Message.tenant_id == tenant_id,
            Message.id == message_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_call_event_message(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        call_id: UUID,
    ) -> Message | None:
        stmt = select(Message).where(
            Message.tenant_id == tenant_id,
            Message.conversation_id == conversation_id,
            Message.kind == MessageKind.CALL_EVENT.value,
            Message.system_payload["call_id"].astext == str(call_id),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_client_id(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        sender_id: UUID,
        client_message_id: str,
    ) -> Message | None:
        stmt = select(Message).where(
            Message.tenant_id == tenant_id,
            Message.conversation_id == conversation_id,
            Message.sender_id == sender_id,
            Message.client_message_id == client_message_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_keyset(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        *,
        before_seq: int | None = None,
        after_seq: int | None = None,
        limit: int = 50,
    ) -> list[Message]:
        stmt = select(Message).where(
            Message.tenant_id == tenant_id,
            Message.conversation_id == conversation_id,
        )
        if before_seq is not None:
            stmt = stmt.where(Message.seq < before_seq).order_by(Message.seq.desc())
        elif after_seq is not None:
            stmt = stmt.where(Message.seq > after_seq).order_by(Message.seq.asc())
        else:
            stmt = stmt.order_by(Message.seq.desc())
        stmt = stmt.limit(limit + 1)
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())
        if before_seq is not None or after_seq is None:
            rows.reverse()
        return rows

    async def create(self, row: Message) -> Message:
        self.session.add(row)
        await self.session.flush()
        return row

    async def update(self, row: Message, values: dict) -> Message:
        for key, value in values.items():
            setattr(row, key, value)
        await self.session.flush()
        return row

    async def attachments_for_messages(
        self, tenant_id: UUID, message_ids: list[UUID]
    ) -> dict[UUID, Attachment]:
        if not message_ids:
            return {}
        stmt = select(Attachment).where(
            Attachment.tenant_id == tenant_id,
            Attachment.entity_type == AttachmentEntityType.CHAT_MESSAGE.value,
            Attachment.entity_id.in_(message_ids),
        )
        result = await self.session.execute(stmt)
        return {attachment.entity_id: attachment for attachment in result.scalars().all()}

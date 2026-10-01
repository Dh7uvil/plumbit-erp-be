"""Chat message attachment repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.communication.extended.models import ChatMessageAttachment


class ChatMessageAttachmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, tenant_id: UUID, attachment_id: UUID
    ) -> ChatMessageAttachment | None:
        stmt = select(ChatMessageAttachment).where(
            ChatMessageAttachment.tenant_id == tenant_id,
            ChatMessageAttachment.attachment_id == attachment_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, row: ChatMessageAttachment) -> ChatMessageAttachment:
        self.session.add(row)
        await self.session.flush()
        return row

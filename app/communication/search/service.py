"""Communication search use cases."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.common.attachments.models import Attachment
from app.communication.conversations.models import Conversation, ConversationParticipant
from app.communication.conversations.service import ConversationService
from app.communication.messages.models import Message
from app.communication.messages.schemas import MessageResponse
from app.communication.search.schemas import SearchResponse, SearchResultItem, SearchType
from app.communication.shared.feature import require_communication_enabled
from app.core.enums import AttachmentEntityType, ConversationKind, MessageKind
from app.core.exceptions import ValidationError


class SearchService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.conversations = ConversationService(session)

    async def search(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        q: str,
        search_type: SearchType,
        limit: int = 50,
    ) -> SearchResponse:
        require_communication_enabled()
        query = q.strip()
        if not query:
            raise ValidationError("Search query is required")
        limit = min(limit, 100)

        if search_type == SearchType.MESSAGES:
            results = await self._search_messages(tenant_id, user_id, query, limit)
        elif search_type == SearchType.PEOPLE:
            results = await self._search_people(tenant_id, user_id, query, limit)
        elif search_type == SearchType.GROUPS:
            results = await self._search_groups(tenant_id, user_id, query, limit)
        elif search_type == SearchType.FILES:
            results = await self._search_files(tenant_id, user_id, query, limit)
        elif search_type == SearchType.CONVERSATIONS:
            results = await self._search_conversations(tenant_id, user_id, query, limit)
        else:
            raise ValidationError("Invalid search type")

        return SearchResponse(results=results)

    async def search_conversation_messages(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        user_id: UUID,
        *,
        q: str,
        limit: int = 50,
    ) -> list[MessageResponse]:
        require_communication_enabled()
        query = q.strip()
        if not query:
            raise ValidationError("Search query is required")
        await self.conversations.require_participant(tenant_id, conversation_id, user_id)
        limit = min(limit, 100)
        stmt = (
            select(Message)
            .where(
                Message.tenant_id == tenant_id,
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None),
                text("messages.search_vector @@ plainto_tsquery('simple', :q)"),
            )
            .order_by(Message.seq.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt, {"q": query})
        rows = list(result.scalars().all())
        rows.reverse()
        return [MessageResponse.model_validate(row) for row in rows]

    def _member_conversations_subquery(
        self, tenant_id: UUID, user_id: UUID
    ) -> Select[tuple[UUID]]:
        return (
            select(ConversationParticipant.conversation_id)
            .where(
                ConversationParticipant.tenant_id == tenant_id,
                ConversationParticipant.user_id == user_id,
                ConversationParticipant.left_at.is_(None),
            )
            .distinct()
        )

    async def _search_messages(
        self, tenant_id: UUID, user_id: UUID, query: str, limit: int
    ) -> list[SearchResultItem]:
        member_ids = self._member_conversations_subquery(tenant_id, user_id)
        stmt = (
            select(Message, Conversation.name)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.tenant_id == tenant_id,
                Message.conversation_id.in_(member_ids),
                Message.deleted_at.is_(None),
                text("messages.search_vector @@ plainto_tsquery('simple', :q)"),
            )
            .order_by(Message.seq.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt, {"q": query})
        items: list[SearchResultItem] = []
        for message, conversation_name in result.all():
            preview = (message.body or "")[:120]
            items.append(
                SearchResultItem(
                    type=SearchType.MESSAGES,
                    id=message.id,
                    title=conversation_name or "Direct message",
                    subtitle=preview or None,
                    conversation_id=message.conversation_id,
                    seq=message.seq,
                    highlight=preview or None,
                )
            )
        return items

    async def _search_people(
        self, tenant_id: UUID, user_id: UUID, query: str, limit: int
    ) -> list[SearchResultItem]:
        term = f"%{query}%"
        stmt = (
            select(User)
            .where(
                User.tenant_id == tenant_id,
                User.status.in_(("ACTIVE", "INVITED")),
                User.id != user_id,
                or_(User.name.ilike(term), User.email.ilike(term)),
            )
            .order_by(User.name.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [
            SearchResultItem(
                type=SearchType.PEOPLE,
                id=user.id,
                title=user.name,
                subtitle=user.email,
            )
            for user in result.scalars().all()
        ]

    async def _search_groups(
        self, tenant_id: UUID, user_id: UUID, query: str, limit: int
    ) -> list[SearchResultItem]:
        member_ids = self._member_conversations_subquery(tenant_id, user_id)
        term = f"%{query}%"
        stmt = (
            select(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.deleted_at.is_(None),
                Conversation.kind == ConversationKind.GROUP.value,
                Conversation.id.in_(member_ids),
                or_(
                    Conversation.name.ilike(term),
                    Conversation.description.ilike(term),
                ),
            )
            .order_by(Conversation.last_message_at.desc().nullslast())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [
            SearchResultItem(
                type=SearchType.GROUPS,
                id=conv.id,
                title=conv.name or "Group",
                subtitle=conv.description,
                conversation_id=conv.id,
            )
            for conv in result.scalars().all()
        ]

    async def _search_files(
        self, tenant_id: UUID, user_id: UUID, query: str, limit: int
    ) -> list[SearchResultItem]:
        member_ids = self._member_conversations_subquery(tenant_id, user_id)
        term = f"%{query}%"
        stmt = (
            select(Attachment, Message)
            .join(Message, Attachment.entity_id == Message.id)
            .where(
                Attachment.tenant_id == tenant_id,
                Attachment.entity_type == AttachmentEntityType.CHAT_MESSAGE.value,
                Message.conversation_id.in_(member_ids),
                Message.kind == MessageKind.ATTACHMENT.value,
                Message.deleted_at.is_(None),
                Attachment.original_filename.ilike(term),
            )
            .order_by(Message.seq.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        items: list[SearchResultItem] = []
        for attachment, message in result.all():
            items.append(
                SearchResultItem(
                    type=SearchType.FILES,
                    id=attachment.id,
                    title=attachment.original_filename,
                    subtitle=attachment.content_type,
                    conversation_id=message.conversation_id,
                    seq=message.seq,
                )
            )
        return items

    async def _search_conversations(
        self, tenant_id: UUID, user_id: UUID, query: str, limit: int
    ) -> list[SearchResultItem]:
        member_ids = self._member_conversations_subquery(tenant_id, user_id)
        term = f"%{query}%"
        stmt = (
            select(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.deleted_at.is_(None),
                Conversation.id.in_(member_ids),
                or_(
                    Conversation.name.ilike(term),
                    Conversation.description.ilike(term),
                ),
            )
            .order_by(Conversation.last_message_at.desc().nullslast())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [
            SearchResultItem(
                type=SearchType.CONVERSATIONS,
                id=conv.id,
                title=conv.name or ("Direct message" if conv.kind == ConversationKind.DIRECT.value else "Group"),
                subtitle=conv.description,
                conversation_id=conv.id,
            )
            for conv in result.scalars().all()
        ]

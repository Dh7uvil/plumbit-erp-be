"""Conversation repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.communication.conversations.models import Conversation, ConversationParticipant
from app.core.enums import ConversationKind


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Conversation,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "last_message_at", "name", "kind"}
            ),
            allowed_filter_fields=frozenset({"kind"}),
        )

    async def get(self, tenant_id: UUID, conversation_id: UUID) -> Conversation | None:
        return await self._repo.get(tenant_id, conversation_id)

    async def get_by_direct_key(
        self, tenant_id: UUID, direct_key: str
    ) -> Conversation | None:
        stmt = select(Conversation).where(
            Conversation.tenant_id == tenant_id,
            Conversation.direct_key == direct_key,
            Conversation.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_context(
        self,
        tenant_id: UUID,
        context_entity_type: str,
        context_entity_id: UUID,
    ) -> Conversation | None:
        stmt = select(Conversation).where(
            Conversation.tenant_id == tenant_id,
            Conversation.context_entity_type == context_entity_type,
            Conversation.context_entity_id == context_entity_id,
            Conversation.kind == ConversationKind.GROUP.value,
            Conversation.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        kind: str | None = None,
    ) -> tuple[list[tuple[Conversation, ConversationParticipant]], int]:
        base = (
            select(Conversation, ConversationParticipant)
            .join(
                ConversationParticipant,
                ConversationParticipant.conversation_id == Conversation.id,
            )
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.deleted_at.is_(None),
                ConversationParticipant.tenant_id == tenant_id,
                ConversationParticipant.user_id == user_id,
                ConversationParticipant.left_at.is_(None),
            )
        )
        if kind:
            base = base.where(Conversation.kind == kind)
        if common_filter and common_filter.search:
            term = f"%{common_filter.search.strip()}%"
            base = base.where(Conversation.name.ilike(term))
        count_stmt = select(func.count()).select_from(base.subquery())
        total = int((await self.session.execute(count_stmt)).scalar_one())
        sort_field = common_filter.sort_by if common_filter else "last_message_at"
        sort_order = common_filter.sort_order if common_filter else "desc"
        order_col = getattr(Conversation, sort_field, Conversation.last_message_at)
        order = order_col.desc() if sort_order == "desc" else order_col.asc()
        stmt = base.order_by(order).offset(page.offset).limit(page.page_size)
        rows = list((await self.session.execute(stmt)).all())
        return rows, total

    async def create(self, tenant_id: UUID, values: dict) -> Conversation:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, conversation_id: UUID, values: dict
    ) -> Conversation | None:
        return await self._repo.update(tenant_id, conversation_id, values)

    async def soft_delete(self, tenant_id: UUID, conversation_id: UUID) -> bool:
        return await self._repo.soft_delete(tenant_id, conversation_id)

    async def lock_for_update(self, tenant_id: UUID, conversation_id: UUID) -> Conversation | None:
        stmt = (
            select(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.id == conversation_id,
                Conversation.deleted_at.is_(None),
            )
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class ConversationParticipantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, tenant_id: UUID, conversation_id: UUID, user_id: UUID
    ) -> ConversationParticipant | None:
        stmt = select(ConversationParticipant).where(
            ConversationParticipant.tenant_id == tenant_id,
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(
        self, tenant_id: UUID, conversation_id: UUID
    ) -> list[ConversationParticipant]:
        rows = await self.list_active_for_conversations(tenant_id, [conversation_id])
        return rows.get(conversation_id, [])

    async def list_active_for_conversations(
        self, tenant_id: UUID, conversation_ids: list[UUID]
    ) -> dict[UUID, list[ConversationParticipant]]:
        if not conversation_ids:
            return {}
        stmt = select(ConversationParticipant).where(
            ConversationParticipant.tenant_id == tenant_id,
            ConversationParticipant.conversation_id.in_(conversation_ids),
            ConversationParticipant.left_at.is_(None),
        )
        result = await self.session.execute(stmt)
        grouped: dict[UUID, list[ConversationParticipant]] = {
            conversation_id: [] for conversation_id in conversation_ids
        }
        for participant in result.scalars().all():
            grouped.setdefault(participant.conversation_id, []).append(participant)
        return grouped

    async def add(self, row: ConversationParticipant) -> ConversationParticipant:
        self.session.add(row)
        await self.session.flush()
        return row

    async def update_participant(
        self, participant: ConversationParticipant, values: dict
    ) -> ConversationParticipant:
        for key, value in values.items():
            setattr(participant, key, value)
        await self.session.flush()
        return participant

    async def count_active(self, tenant_id: UUID, conversation_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(ConversationParticipant)
            .where(
                ConversationParticipant.tenant_id == tenant_id,
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.left_at.is_(None),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_admins(self, tenant_id: UUID, conversation_id: UUID) -> int:
        from app.core.enums import ParticipantRole

        stmt = (
            select(func.count())
            .select_from(ConversationParticipant)
            .where(
                ConversationParticipant.tenant_id == tenant_id,
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.left_at.is_(None),
                ConversationParticipant.role.in_(
                    (ParticipantRole.OWNER.value, ParticipantRole.ADMIN.value)
                ),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())

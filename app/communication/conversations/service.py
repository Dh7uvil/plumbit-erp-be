"""Conversation use cases."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.communication.conversations.models import Conversation, ConversationParticipant
from app.communication.conversations.repository import (
    ConversationParticipantRepository,
    ConversationRepository,
)
from app.communication.conversations.schemas import (
    ConversationCreate,
    ConversationForContextCreate,
    ConversationResponse,
    ConversationUpdate,
    LastMessagePreview,
    MySettingsUpdate,
    ParticipantAdd,
    ParticipantResponse,
    ParticipantRoleUpdate,
    UnreadSummaryResponse,
)
from app.communication.messages.repository import MessageRepository
from app.communication.shared.direct_key import build_direct_key
from app.communication.shared.feature import require_communication_enabled
from app.communication.shared.notifications import CommunicationNotificationService
from app.communication.shared.rate_limit import enforce_typing_rate_limit
from app.communication.shared.signaling_publisher import (
    build_event,
    flush_pending_signaling,
    schedule_inbox_signaling_events,
    schedule_signaling_event,
)
from app.communication.shared.unread import unread_count
from app.core.config import get_settings
from app.core.enums import ConversationKind, ParticipantRole
from app.core.exceptions import PermissionDeniedError, ResourceNotFoundError, ValidationError
from app.db.session import transaction
from app.integrations.agora.channels import conversation_channel_name


class ConversationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ConversationRepository(session)
        self.participants = ConversationParticipantRepository(session)
        self.messages = MessageRepository(session)
        self.notifications = CommunicationNotificationService(session)

    async def list(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        kind: str | None = None,
    ) -> tuple[list[ConversationResponse], int]:
        require_communication_enabled()
        rows, total = await self.repo.list_for_user(
            tenant_id, user_id, page=page, common_filter=common_filter, kind=kind
        )
        conversation_ids = [conv.id for conv, _ in rows]
        participants_by_conversation = await self.participants.list_active_for_conversations(
            tenant_id, conversation_ids
        )
        last_message_ids = [
            conv.last_message_id for conv, _ in rows if conv.last_message_id is not None
        ]
        last_messages = await self.messages.get_many(tenant_id, last_message_ids)
        return [
            self._to_response(
                conv,
                part,
                participants=participants_by_conversation.get(conv.id, []),
                last_message=(
                    LastMessagePreview(
                        id=row.id,
                        sender_id=row.sender_id,
                        body=row.body,
                        kind=row.kind,
                        created_at=row.created_at,
                    )
                    if conv.last_message_id is not None
                    and (row := last_messages.get(conv.last_message_id)) is not None
                    else None
                ),
            )
            for conv, part in rows
        ], total

    async def create(
        self,
        tenant_id: UUID,
        payload: ConversationCreate,
        *,
        actor_user_id: UUID,
    ) -> ConversationResponse:
        require_communication_enabled()
        async with transaction(self.session):
            if payload.kind == ConversationKind.DIRECT:
                other_id = payload.other_user_id
                if other_id is None and payload.participant_user_ids:
                    other_id = payload.participant_user_ids[0]
                if other_id is None or other_id == actor_user_id:
                    raise ValidationError("Direct conversations require another user")
                await self._assert_user_in_tenant(tenant_id, other_id)
                direct_key = build_direct_key(actor_user_id, other_id)
                existing = await self.repo.get_by_direct_key(tenant_id, direct_key)
                if existing:
                    part = await self.participants.get(tenant_id, existing.id, actor_user_id)
                    if part is None:
                        raise ResourceNotFoundError("Conversation not found")
                    participants = await self.participants.list_active(tenant_id, existing.id)
                    return self._to_response(existing, part, participants=participants)
                conversation = await self._create_conversation(
                    tenant_id,
                    kind=ConversationKind.DIRECT.value,
                    name=None,
                    description=None,
                    direct_key=direct_key,
                    actor_user_id=actor_user_id,
                )
                await self._add_participant(
                    tenant_id, conversation.id, actor_user_id, ParticipantRole.OWNER, actor_user_id
                )
                await self._add_participant(
                    tenant_id, conversation.id, other_id, ParticipantRole.MEMBER, actor_user_id
                )
            else:
                if not payload.name:
                    raise ValidationError("Group conversations require a name")
                conversation = await self._create_conversation(
                    tenant_id,
                    kind=ConversationKind.GROUP.value,
                    name=payload.name,
                    description=payload.description,
                    direct_key=None,
                    actor_user_id=actor_user_id,
                )
                await self._add_participant(
                    tenant_id, conversation.id, actor_user_id, ParticipantRole.OWNER, actor_user_id
                )
                for uid in payload.participant_user_ids:
                    if uid == actor_user_id:
                        continue
                    await self._assert_user_in_tenant(tenant_id, uid)
                    await self._add_participant(
                        tenant_id, conversation.id, uid, ParticipantRole.MEMBER, actor_user_id
                    )
            part = await self.participants.get(tenant_id, conversation.id, actor_user_id)
            assert part is not None
            schedule_signaling_event(
                self.session,
                build_event(
                    event_type="conversation.created",
                    tenant_id=tenant_id,
                    actor_id=actor_user_id,
                    conversation_id=conversation.id,
                ),
            )
        await flush_pending_signaling(self.session)
        participants = await self.participants.list_active(tenant_id, conversation.id)
        return self._to_response(conversation, part, participants=participants)

    async def find_or_create_for_context(
        self,
        tenant_id: UUID,
        payload: ConversationForContextCreate,
        *,
        actor_user_id: UUID,
    ) -> ConversationResponse:
        require_communication_enabled()
        existing = await self.repo.get_by_context(
            tenant_id, payload.context_entity_type, payload.context_entity_id
        )
        if existing is not None:
            part = await self.participants.get(tenant_id, existing.id, actor_user_id)
            if part is None or part.left_at is not None:
                async with transaction(self.session):
                    await self._add_participant(
                        tenant_id,
                        existing.id,
                        actor_user_id,
                        ParticipantRole.MEMBER,
                        actor_user_id,
                    )
                    part = await self.participants.get(
                        tenant_id, existing.id, actor_user_id
                    )
            if payload.participant_user_ids:
                assert part is not None
                self._require_admin(part)
            async with transaction(self.session):
                for uid in payload.participant_user_ids:
                    if uid == actor_user_id:
                        continue
                    await self._assert_user_in_tenant(tenant_id, uid)
                    member = await self.participants.get(tenant_id, existing.id, uid)
                    if member is None or member.left_at is not None:
                        await self._add_participant(
                            tenant_id,
                            existing.id,
                            uid,
                            ParticipantRole.MEMBER,
                            actor_user_id,
                        )
            await flush_pending_signaling(self.session)
            part = await self.participants.get(tenant_id, existing.id, actor_user_id)
            assert part is not None
            participants = await self.participants.list_active(tenant_id, existing.id)
            return self._to_response(existing, part, participants=participants)

        name = payload.name or f"{payload.context_entity_type} chat"
        async with transaction(self.session):
            conversation = await self._create_conversation(
                tenant_id,
                kind=ConversationKind.GROUP.value,
                name=name,
                description=None,
                direct_key=None,
                actor_user_id=actor_user_id,
            )
            conversation = await self.repo.update(
                tenant_id,
                conversation.id,
                {
                    "context_entity_type": payload.context_entity_type,
                    "context_entity_id": payload.context_entity_id,
                },
            ) or conversation
            await self._add_participant(
                tenant_id,
                conversation.id,
                actor_user_id,
                ParticipantRole.OWNER,
                actor_user_id,
            )
            for uid in payload.participant_user_ids:
                if uid == actor_user_id:
                    continue
                await self._assert_user_in_tenant(tenant_id, uid)
                await self._add_participant(
                    tenant_id,
                    conversation.id,
                    uid,
                    ParticipantRole.MEMBER,
                    actor_user_id,
                )
            schedule_signaling_event(
                self.session,
                build_event(
                    event_type="conversation.created",
                    tenant_id=tenant_id,
                    actor_id=actor_user_id,
                    conversation_id=conversation.id,
                ),
            )
        await flush_pending_signaling(self.session)
        part = await self.participants.get(tenant_id, conversation.id, actor_user_id)
        assert part is not None
        participants = await self.participants.list_active(tenant_id, conversation.id)
        return self._to_response(conversation, part, participants=participants)

    async def get(
        self, tenant_id: UUID, conversation_id: UUID, user_id: UUID
    ) -> ConversationResponse:
        require_communication_enabled()
        conv, part = await self._require_member(tenant_id, conversation_id, user_id)
        participants = await self.participants.list_active(tenant_id, conversation_id)
        return self._to_response(conv, part, participants=participants)

    async def update(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        payload: ConversationUpdate,
        *,
        actor_user_id: UUID,
    ) -> ConversationResponse:
        require_communication_enabled()
        async with transaction(self.session):
            conv, part = await self._require_member(tenant_id, conversation_id, actor_user_id)
            self._require_admin(part)
            values = payload.model_dump(exclude_unset=True)
            if values:
                conv = await self.repo.update(tenant_id, conversation_id, values) or conv
            schedule_signaling_event(
                self.session,
                build_event(
                    event_type="conversation.updated",
                    tenant_id=tenant_id,
                    actor_id=actor_user_id,
                    conversation_id=conversation_id,
                    data=values,
                ),
            )
        await flush_pending_signaling(self.session)
        return self._to_response(conv, part)

    async def delete(
        self, tenant_id: UUID, conversation_id: UUID, *, actor_user_id: UUID
    ) -> None:
        require_communication_enabled()
        async with transaction(self.session):
            _, part = await self._require_member(tenant_id, conversation_id, actor_user_id)
            if part.role != ParticipantRole.OWNER.value:
                raise PermissionDeniedError()
            await self.repo.soft_delete(tenant_id, conversation_id)

    async def add_participant(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        payload: ParticipantAdd,
        *,
        actor_user_id: UUID,
    ) -> ParticipantResponse:
        require_communication_enabled()
        async with transaction(self.session):
            conv, part = await self._require_member(tenant_id, conversation_id, actor_user_id)
            self._require_admin(part)
            if conv.kind != ConversationKind.GROUP.value:
                raise ValidationError("Cannot add participants to a direct conversation")
            await self._assert_user_in_tenant(tenant_id, payload.user_id)
            row = await self._add_participant(
                tenant_id,
                conversation_id,
                payload.user_id,
                payload.role,
                actor_user_id,
            )
            schedule_signaling_event(
                self.session,
                build_event(
                    event_type="participant.added",
                    tenant_id=tenant_id,
                    actor_id=actor_user_id,
                    conversation_id=conversation_id,
                    data={"user_id": str(payload.user_id), "role": payload.role.value},
                ),
            )
            if conv.kind == ConversationKind.GROUP.value:
                inviter_name = await self._user_display_name(tenant_id, actor_user_id)
                await self.notifications.notify_group_invite(
                    tenant_id,
                    user_id=payload.user_id,
                    conversation_id=conversation_id,
                    conversation_name=conv.name or "Group chat",
                    inviter_name=inviter_name,
                )
        await flush_pending_signaling(self.session)
        return ParticipantResponse.model_validate(row)

    async def update_participant_role(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        user_id: UUID,
        payload: ParticipantRoleUpdate,
        *,
        actor_user_id: UUID,
    ) -> ParticipantResponse:
        require_communication_enabled()
        async with transaction(self.session):
            _, part = await self._require_member(tenant_id, conversation_id, actor_user_id)
            self._require_admin(part)
            target = await self.participants.get(tenant_id, conversation_id, user_id)
            if target is None or target.left_at is not None:
                raise ResourceNotFoundError("Participant not found")
            target = await self.participants.update_participant(
                target, {"role": payload.role.value}
            )
            schedule_signaling_event(
                self.session,
                build_event(
                    event_type="participant.role_changed",
                    tenant_id=tenant_id,
                    actor_id=actor_user_id,
                    conversation_id=conversation_id,
                    data={"user_id": str(user_id), "role": payload.role.value},
                ),
            )
        await flush_pending_signaling(self.session)
        return ParticipantResponse.model_validate(target)

    async def remove_participant(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        user_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> None:
        require_communication_enabled()
        async with transaction(self.session):
            _, part = await self._require_member(tenant_id, conversation_id, actor_user_id)
            if user_id != actor_user_id:
                self._require_admin(part)
            target = await self.participants.get(tenant_id, conversation_id, user_id)
            if target is None or target.left_at is not None:
                raise ResourceNotFoundError("Participant not found")
            from app.common.utils.datetime import utcnow

            await self.participants.update_participant(target, {"left_at": utcnow()})
            schedule_signaling_event(
                self.session,
                build_event(
                    event_type="participant.removed",
                    tenant_id=tenant_id,
                    actor_id=actor_user_id,
                    conversation_id=conversation_id,
                    data={"user_id": str(user_id)},
                ),
            )
        await flush_pending_signaling(self.session)

    async def leave(
        self, tenant_id: UUID, conversation_id: UUID, *, actor_user_id: UUID
    ) -> None:
        await self.remove_participant(
            tenant_id, conversation_id, actor_user_id, actor_user_id=actor_user_id
        )

    async def update_my_settings(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        payload: MySettingsUpdate,
        *,
        actor_user_id: UUID,
    ) -> ParticipantResponse:
        require_communication_enabled()
        async with transaction(self.session):
            _, part = await self._require_member(tenant_id, conversation_id, actor_user_id)
            values = payload.model_dump(exclude_unset=True)
            part = await self.participants.update_participant(part, values)
        return ParticipantResponse.model_validate(part)

    async def mark_read(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        *,
        actor_user_id: UUID,
        up_to_seq: int,
    ) -> None:
        require_communication_enabled()
        async with transaction(self.session):
            conv, part = await self._require_member(tenant_id, conversation_id, actor_user_id)
            new_seq = min(up_to_seq, conv.message_seq)
            if new_seq > part.last_read_seq:
                await self.participants.update_participant(part, {"last_read_seq": new_seq})
                participants = await self.participants.list_active(tenant_id, conversation_id)
                schedule_inbox_signaling_events(
                    self.session,
                    build_event(
                        event_type="message.read",
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

    async def typing(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        *,
        actor_user_id: UUID,
        is_typing: bool,
    ) -> None:
        require_communication_enabled()
        enforce_typing_rate_limit(str(actor_user_id), str(conversation_id))
        await self._require_member(tenant_id, conversation_id, actor_user_id)
        schedule_signaling_event(
            self.session,
            build_event(
                event_type="typing.started" if is_typing else "typing.stopped",
                tenant_id=tenant_id,
                actor_id=actor_user_id,
                conversation_id=conversation_id,
            ),
        )
        await flush_pending_signaling(self.session)

    async def unread_summary(
        self, tenant_id: UUID, user_id: UUID
    ) -> UnreadSummaryResponse:
        require_communication_enabled()
        page = PageParams(page=1, page_size=500)
        rows, _ = await self.repo.list_for_user(tenant_id, user_id, page=page)
        items: list[dict[str, object]] = []
        total = 0
        for conv, part in rows:
            count = unread_count(conv.message_seq, part.last_read_seq)
            total += count
            if count:
                items.append({"conversation_id": str(conv.id), "unread_count": count})
        return UnreadSummaryResponse(total_unread=total, conversations=items)

    async def require_participant(
        self, tenant_id: UUID, conversation_id: UUID, user_id: UUID
    ) -> ConversationParticipant:
        part = await self.participants.get(tenant_id, conversation_id, user_id)
        if part is None or part.left_at is not None:
            raise ResourceNotFoundError("Conversation not found")
        return part

    async def _create_conversation(
        self,
        tenant_id: UUID,
        *,
        kind: str,
        name: str | None,
        description: str | None,
        direct_key: str | None,
        actor_user_id: UUID,
    ) -> Conversation:
        from uuid import uuid4

        conv_id = uuid4()
        channel = conversation_channel_name(tenant_id, conv_id)
        row = Conversation(
            id=conv_id,
            tenant_id=tenant_id,
            kind=kind,
            name=name,
            description=description,
            direct_key=direct_key,
            channel_name=channel,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def _add_participant(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        user_id: UUID,
        role: ParticipantRole,
        added_by: UUID,
    ) -> ConversationParticipant:
        existing = await self.participants.get(tenant_id, conversation_id, user_id)
        if existing is not None:
            if existing.left_at is None:
                return existing
            return await self.participants.update_participant(
                existing, {"left_at": None, "role": role.value, "added_by": added_by}
            )
        return await self.participants.add(
            ConversationParticipant(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                user_id=user_id,
                role=role.value,
                added_by=added_by,
            )
        )

    async def _require_member(
        self, tenant_id: UUID, conversation_id: UUID, user_id: UUID
    ) -> tuple[Conversation, ConversationParticipant]:
        conv = await self.repo.get(tenant_id, conversation_id)
        if conv is None:
            raise ResourceNotFoundError("Conversation not found")
        part = await self.require_participant(tenant_id, conversation_id, user_id)
        return conv, part

    async def _user_display_name(self, tenant_id: UUID, user_id: UUID) -> str:
        from sqlalchemy import select

        stmt = select(User.name).where(User.tenant_id == tenant_id, User.id == user_id)
        result = await self.session.execute(stmt)
        name = result.scalar_one_or_none()
        return name or "Someone"

    async def _assert_user_in_tenant(self, tenant_id: UUID, user_id: UUID) -> None:
        from sqlalchemy import select

        stmt = select(User.id).where(User.tenant_id == tenant_id, User.id == user_id)
        result = await self.session.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise ValidationError("User is not in this tenant")

    @staticmethod
    def _require_admin(part: ConversationParticipant) -> None:
        if part.role not in (ParticipantRole.OWNER.value, ParticipantRole.ADMIN.value):
            raise PermissionDeniedError()

    def _to_response(
        self,
        conv: Conversation,
        part: ConversationParticipant,
        *,
        participants: list[ConversationParticipant] | None = None,
        last_message: LastMessagePreview | None = None,
    ) -> ConversationResponse:
        response = ConversationResponse.model_validate(conv)
        response.unread_count = unread_count(conv.message_seq, part.last_read_seq)
        response.last_message = last_message
        if participants is not None:
            response.participants = [
                ParticipantResponse.model_validate(row) for row in participants
            ]
        return response

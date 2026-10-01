"""Group conversation use cases."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import COMMUNICATION_MODULE, GROUP_MANAGE
from app.common.services.audit import AuditWriter
from app.communication.conversations.models import Conversation, ConversationParticipant
from app.communication.conversations.repository import ConversationRepository
from app.communication.conversations.schemas import ConversationCreate, ConversationResponse, ParticipantResponse
from app.communication.conversations.service import ConversationService
from app.communication.groups.schemas import (
    GroupCreate,
    GroupMembersAdd,
    GroupResponse,
    GroupUpdate,
)
from app.communication.messages.models import Message
from app.communication.messages.repository import MessageRepository
from app.communication.shared.feature import require_communication_enabled
from app.communication.shared.signaling_publisher import (
    build_event,
    flush_pending_signaling,
    schedule_signaling_event,
)
from app.core.config import get_settings
from app.core.enums import AuditAction, ConversationKind, MessageKind, ParticipantRole
from app.core.exceptions import PermissionDeniedError, ResourceNotFoundError, ValidationError
from app.core.permissions import has_permission
from app.db.session import transaction


class GroupService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.conversations = ConversationService(session)
        self.repo = ConversationRepository(session)
        self.messages = MessageRepository(session)
        self.audit = AuditWriter(session)

    async def create(
        self,
        tenant_id: UUID,
        payload: GroupCreate,
        *,
        actor_user_id: UUID,
        actor_permissions: frozenset[str],
    ) -> GroupResponse:
        require_communication_enabled()
        settings = get_settings()
        max_members = payload.max_members or settings.chat_max_group_members
        if max_members > settings.chat_max_group_members:
            raise ValidationError(
                f"max_members cannot exceed {settings.chat_max_group_members}"
            )
        member_ids = list(dict.fromkeys(payload.member_user_ids))
        if actor_user_id in member_ids:
            member_ids.remove(actor_user_id)
        total = 1 + len(member_ids)
        if total > max_members:
            raise ValidationError("Member count exceeds max_members")

        conv_payload = ConversationCreate(
            kind=ConversationKind.GROUP,
            name=payload.name,
            description=payload.description,
            participant_user_ids=member_ids,
        )
        response = await self.conversations.create(
            tenant_id, conv_payload, actor_user_id=actor_user_id
        )
        conv = await self.repo.get(tenant_id, response.id)
        assert conv is not None
        async with transaction(self.session):
            if max_members != conv.max_members:
                conv = await self.repo.update(
                    tenant_id, conv.id, {"max_members": max_members}
                ) or conv
            await self._emit_system_message(
                tenant_id,
                conv.id,
                event="group_created",
                actor_user_id=actor_user_id,
                payload={"name": payload.name},
            )
        await flush_pending_signaling(self.session)
        response = await self.conversations.get(tenant_id, conv.id, actor_user_id)
        return self._to_group_response(conv, response)

    async def update(
        self,
        tenant_id: UUID,
        group_id: UUID,
        payload: GroupUpdate,
        *,
        actor_user_id: UUID,
        actor_permissions: frozenset[str],
    ) -> GroupResponse:
        require_communication_enabled()
        async with transaction(self.session):
            conv, part = await self._require_group(tenant_id, group_id, actor_user_id)
            if conv.only_admins_can_edit_info and not self._can_manage_group(
                part, actor_permissions
            ):
                raise PermissionDeniedError()
            values = payload.model_dump(exclude_unset=True)
            if values:
                conv = await self.repo.update(tenant_id, group_id, values) or conv
                schedule_signaling_event(
                    self.session,
                    build_event(
                        event_type="conversation.updated",
                        tenant_id=tenant_id,
                        actor_id=actor_user_id,
                        conversation_id=group_id,
                        data=values,
                    ),
                )
        await flush_pending_signaling(self.session)
        return await self._group_response(tenant_id, group_id, actor_user_id)

    async def add_members(
        self,
        tenant_id: UUID,
        group_id: UUID,
        payload: GroupMembersAdd,
        *,
        actor_user_id: UUID,
        actor_permissions: frozenset[str],
    ) -> GroupResponse:
        require_communication_enabled()
        async with transaction(self.session):
            conv, part = await self._require_group(tenant_id, group_id, actor_user_id)
            if not self._can_manage_group(part, actor_permissions):
                raise PermissionDeniedError()
            unique_ids = list(dict.fromkeys(payload.user_ids))
            active_count = await self.conversations.participants.count_active(
                tenant_id, group_id
            )
            pending_additions = 0
            for user_id in unique_ids:
                if user_id == actor_user_id:
                    continue
                await self.conversations._assert_user_in_tenant(tenant_id, user_id)
                existing = await self.conversations.participants.get(
                    tenant_id, group_id, user_id
                )
                if existing is not None and existing.left_at is None:
                    continue
                pending_additions += 1
            if active_count + pending_additions > conv.max_members:
                raise ValidationError("Adding members would exceed max_members")
            for user_id in unique_ids:
                if user_id == actor_user_id:
                    continue
                existing = await self.conversations.participants.get(
                    tenant_id, group_id, user_id
                )
                if existing is not None and existing.left_at is None:
                    continue
                await self.conversations._add_participant(
                    tenant_id,
                    group_id,
                    user_id,
                    ParticipantRole.MEMBER,
                    actor_user_id,
                )
                schedule_signaling_event(
                    self.session,
                    build_event(
                        event_type="participant.added",
                        tenant_id=tenant_id,
                        actor_id=actor_user_id,
                        conversation_id=group_id,
                        data={"user_id": str(user_id), "role": ParticipantRole.MEMBER.value},
                    ),
                )
                await self._emit_system_message(
                    tenant_id,
                    group_id,
                    event="member_added",
                    actor_user_id=actor_user_id,
                    payload={"user_id": str(user_id)},
                )
                await self.audit.write(
                    tenant_id=tenant_id,
                    action=AuditAction.CREATE,
                    module=COMMUNICATION_MODULE,
                    entity_type="group_member",
                    entity_id=group_id,
                    user_id=actor_user_id,
                    new_values={"user_id": str(user_id), "action": "member_added"},
                )
        await flush_pending_signaling(self.session)
        return await self._group_response(tenant_id, group_id, actor_user_id)

    async def remove_member(
        self,
        tenant_id: UUID,
        group_id: UUID,
        user_id: UUID,
        *,
        actor_user_id: UUID,
        actor_permissions: frozenset[str],
    ) -> GroupResponse:
        require_communication_enabled()
        async with transaction(self.session):
            conv, part = await self._require_group(tenant_id, group_id, actor_user_id)
            if user_id != actor_user_id and not self._can_manage_group(
                part, actor_permissions
            ):
                raise PermissionDeniedError()
            target = await self.conversations.participants.get(tenant_id, group_id, user_id)
            if target is None or target.left_at is not None:
                raise ResourceNotFoundError("Participant not found")
            from app.common.utils.datetime import utcnow

            await self.conversations.participants.update_participant(
                target, {"left_at": utcnow()}
            )
            event = "member_left" if user_id == actor_user_id else "member_removed"
            await self._emit_system_message(
                tenant_id,
                group_id,
                event=event,
                actor_user_id=actor_user_id,
                payload={"user_id": str(user_id)},
            )
            schedule_signaling_event(
                self.session,
                build_event(
                    event_type="participant.removed",
                    tenant_id=tenant_id,
                    actor_id=actor_user_id,
                    conversation_id=group_id,
                    data={"user_id": str(user_id)},
                ),
            )
            await self.audit.write(
                tenant_id=tenant_id,
                action=AuditAction.DELETE,
                module=COMMUNICATION_MODULE,
                entity_type="group_member",
                entity_id=group_id,
                user_id=actor_user_id,
                old_values={"user_id": str(user_id), "action": event},
            )
        await flush_pending_signaling(self.session)
        return await self._group_response(tenant_id, group_id, actor_user_id)

    async def leave(
        self,
        tenant_id: UUID,
        group_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> None:
        require_communication_enabled()
        async with transaction(self.session):
            await self._require_group(tenant_id, group_id, actor_user_id)
            target = await self.conversations.participants.get(
                tenant_id, group_id, actor_user_id
            )
            if target is None or target.left_at is not None:
                raise ResourceNotFoundError("Participant not found")
            if target.role in (
                ParticipantRole.ADMIN.value,
                ParticipantRole.OWNER.value,
            ):
                admin_count = await self.conversations.participants.count_admins(
                    tenant_id, group_id
                )
                if admin_count <= 1:
                    raise ValidationError("Cannot leave as the last admin")
            from app.common.utils.datetime import utcnow

            await self.conversations.participants.update_participant(
                target, {"left_at": utcnow()}
            )
            await self._emit_system_message(
                tenant_id,
                group_id,
                event="member_left",
                actor_user_id=actor_user_id,
                payload={"user_id": str(actor_user_id)},
            )
            schedule_signaling_event(
                self.session,
                build_event(
                    event_type="participant.removed",
                    tenant_id=tenant_id,
                    actor_id=actor_user_id,
                    conversation_id=group_id,
                    data={"user_id": str(actor_user_id)},
                ),
            )
            await self.audit.write(
                tenant_id=tenant_id,
                action=AuditAction.DELETE,
                module=COMMUNICATION_MODULE,
                entity_type="group_member",
                entity_id=group_id,
                user_id=actor_user_id,
                old_values={"user_id": str(actor_user_id), "action": "member_left"},
            )
        await flush_pending_signaling(self.session)

    async def promote_admin(
        self,
        tenant_id: UUID,
        group_id: UUID,
        user_id: UUID,
        *,
        actor_user_id: UUID,
        actor_permissions: frozenset[str],
    ) -> GroupResponse:
        require_communication_enabled()
        async with transaction(self.session):
            _, part = await self._require_group(tenant_id, group_id, actor_user_id)
            if not self._can_manage_group(part, actor_permissions):
                raise PermissionDeniedError()
            target = await self.conversations.participants.get(tenant_id, group_id, user_id)
            if target is None or target.left_at is not None:
                raise ResourceNotFoundError("Participant not found")
            if target.role in (ParticipantRole.ADMIN.value, ParticipantRole.OWNER.value):
                pass
            else:
                await self.conversations.participants.update_participant(
                    target, {"role": ParticipantRole.ADMIN.value}
                )
                await self._emit_system_message(
                    tenant_id,
                    group_id,
                    event="admin_promoted",
                    actor_user_id=actor_user_id,
                    payload={"user_id": str(user_id)},
                )
                schedule_signaling_event(
                    self.session,
                    build_event(
                        event_type="participant.role_changed",
                        tenant_id=tenant_id,
                        actor_id=actor_user_id,
                        conversation_id=group_id,
                        data={"user_id": str(user_id), "role": ParticipantRole.ADMIN.value},
                    ),
                )
                await self.audit.write(
                    tenant_id=tenant_id,
                    action=AuditAction.UPDATE,
                    module=COMMUNICATION_MODULE,
                    entity_type="group_member",
                    entity_id=group_id,
                    user_id=actor_user_id,
                    new_values={
                        "user_id": str(user_id),
                        "action": "admin_promoted",
                        "role": ParticipantRole.ADMIN.value,
                    },
                )
        await flush_pending_signaling(self.session)
        return await self._group_response(tenant_id, group_id, actor_user_id)

    async def demote_admin(
        self,
        tenant_id: UUID,
        group_id: UUID,
        user_id: UUID,
        *,
        actor_user_id: UUID,
        actor_permissions: frozenset[str],
    ) -> GroupResponse:
        require_communication_enabled()
        async with transaction(self.session):
            _, part = await self._require_group(tenant_id, group_id, actor_user_id)
            if not self._can_manage_group(part, actor_permissions):
                raise PermissionDeniedError()
            target = await self.conversations.participants.get(tenant_id, group_id, user_id)
            if target is None or target.left_at is not None:
                raise ResourceNotFoundError("Participant not found")
            if target.role not in (ParticipantRole.ADMIN.value, ParticipantRole.OWNER.value):
                raise ValidationError("User is not an admin")
            admin_count = await self.conversations.participants.count_admins(
                tenant_id, group_id
            )
            if admin_count <= 1:
                raise ValidationError("Cannot demote the last admin")
            await self.conversations.participants.update_participant(
                target, {"role": ParticipantRole.MEMBER.value}
            )
            await self._emit_system_message(
                tenant_id,
                group_id,
                event="admin_demoted",
                actor_user_id=actor_user_id,
                payload={"user_id": str(user_id)},
            )
            schedule_signaling_event(
                self.session,
                build_event(
                    event_type="participant.role_changed",
                    tenant_id=tenant_id,
                    actor_id=actor_user_id,
                    conversation_id=group_id,
                    data={"user_id": str(user_id), "role": ParticipantRole.MEMBER.value},
                ),
            )
            await self.audit.write(
                tenant_id=tenant_id,
                action=AuditAction.UPDATE,
                module=COMMUNICATION_MODULE,
                entity_type="group_member",
                entity_id=group_id,
                user_id=actor_user_id,
                new_values={
                    "user_id": str(user_id),
                    "action": "admin_demoted",
                    "role": ParticipantRole.MEMBER.value,
                },
            )
        await flush_pending_signaling(self.session)
        return await self._group_response(tenant_id, group_id, actor_user_id)

    async def _group_response(
        self, tenant_id: UUID, group_id: UUID, actor_user_id: UUID
    ) -> GroupResponse:
        conv = await self.repo.get(tenant_id, group_id)
        if conv is None:
            raise ResourceNotFoundError("Group not found")
        try:
            base = await self.conversations.get(tenant_id, group_id, actor_user_id)
        except ResourceNotFoundError:
            participants = await self.conversations.participants.list_active(
                tenant_id, group_id
            )
            base = ConversationResponse.model_validate(conv)
            base.unread_count = 0
            base.participants = [
                ParticipantResponse.model_validate(row) for row in participants
            ]
        return self._to_group_response(conv, base)

    async def _require_group(
        self, tenant_id: UUID, group_id: UUID, user_id: UUID
    ) -> tuple[Conversation, ConversationParticipant]:
        conv, part = await self.conversations._require_member(tenant_id, group_id, user_id)
        if conv.kind != ConversationKind.GROUP.value:
            raise ResourceNotFoundError("Group not found")
        return conv, part

    @staticmethod
    def _can_manage_group(
        part: ConversationParticipant, actor_permissions: frozenset[str]
    ) -> bool:
        if has_permission(actor_permissions, GROUP_MANAGE):
            return True
        return part.role in (ParticipantRole.OWNER.value, ParticipantRole.ADMIN.value)

    @staticmethod
    def _to_group_response(conv: Conversation, base) -> GroupResponse:
        return GroupResponse.from_conversation(
            base,
            max_members=conv.max_members,
            only_admins_can_edit_info=conv.only_admins_can_edit_info,
            image_attachment_id=conv.image_attachment_id,
            context_entity_type=conv.context_entity_type,
            context_entity_id=conv.context_entity_id,
        )

    async def _emit_system_message(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        *,
        event: str,
        actor_user_id: UUID,
        payload: dict[str, object],
    ) -> Message:
        conv = await self.repo.lock_for_update(tenant_id, conversation_id)
        if conv is None:
            raise ResourceNotFoundError("Conversation not found")
        seq = conv.message_seq + 1
        system_payload = {"event": event, "actor_id": str(actor_user_id), **payload}
        row = await self.messages.create(
            Message(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                seq=seq,
                sender_id=None,
                kind=MessageKind.SYSTEM.value,
                body=None,
                system_payload=system_payload,
            )
        )
        from app.common.utils.datetime import utcnow

        await self.repo.update(
            tenant_id,
            conversation_id,
            {
                "message_seq": seq,
                "last_message_id": row.id,
                "last_message_at": utcnow(),
            },
        )
        from app.communication.shared.signaling_publisher import schedule_inbox_signaling_events

        participants = await self.conversations.participants.list_active(
            tenant_id, conversation_id
        )
        schedule_inbox_signaling_events(
            self.session,
            build_event(
                event_type="message.created",
                tenant_id=tenant_id,
                actor_id=actor_user_id,
                conversation_id=conversation_id,
                seq=seq,
                data={
                    "id": str(row.id),
                    "kind": MessageKind.SYSTEM.value,
                    "system_payload": system_payload,
                },
            ),
            participant_user_ids=[part.user_id for part in participants],
            actor_user_id=actor_user_id,
        )
        return row

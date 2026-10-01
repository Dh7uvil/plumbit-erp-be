"""Call use cases."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.outbox.service import OutboxService
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.utils.datetime import utcnow
from app.communication.calls.events import CallEventService
from app.communication.calls.models import Call, CallParticipant
from app.communication.calls.outbox_handlers import RING_TIMEOUT_EVENT, ring_timeout_available_at
from app.communication.calls.repository import CallParticipantRepository, CallRepository
from app.communication.messages.service import MessageService
from app.communication.calls.schemas import (
    CallCreate,
    CallMediaUpdate,
    CallParticipantResponse,
    CallResponse,
)
from app.communication.calls.state import transition_call_status, transition_participant_status
from app.communication.conversations.models import Conversation
from app.communication.conversations.schemas import ConversationCreate
from app.communication.conversations.service import ConversationService
from app.communication.shared.feature import require_communication_enabled
from app.communication.shared.notifications import CommunicationNotificationService
from app.communication.shared.rate_limit import enforce_call_create_rate_limit, enforce_token_rate_limit
from app.communication.shared.signaling_publisher import (
    build_event,
    flush_pending_signaling,
    schedule_signaling_event,
)
from app.core.config import get_settings
from app.core.enums import (
    CallEventType,
    CallKind,
    CallParticipantStatus,
    CallScope,
    CallStatus,
    ConversationKind,
)
from app.core.exceptions import PermissionDeniedError, ResourceNotFoundError, ValidationError
from app.db.session import transaction
from app.integrations.agora.channels import call_channel_name
from app.integrations.agora.identity import ChatIdentityService
from app.integrations.agora.tokens import build_rtc_token


class CallService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CallRepository(session)
        self.participants = CallParticipantRepository(session)
        self.conversations = ConversationService(session)
        self.outbox = OutboxService(session)
        self.identity = ChatIdentityService(session)
        self.notifications = CommunicationNotificationService(session)
        self.call_events = CallEventService(session)
        self.messages = MessageService(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        conversation_id: UUID | None = None,
        participant_user_id: UUID | None = None,
    ) -> tuple[list[CallResponse], int]:
        require_communication_enabled()
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            status=status,
            conversation_id=conversation_id,
            participant_user_id=participant_user_id,
        )
        refreshed: list[Call] = []
        for row in rows:
            refreshed.append(await self._expire_stale_ringing_call(tenant_id, row))
        return [await self._to_response(tenant_id, row) for row in refreshed], total

    async def get(
        self, tenant_id: UUID, call_id: UUID, *, actor_user_id: UUID
    ) -> CallResponse:
        require_communication_enabled()
        row, _part = await self._require_participant(tenant_id, call_id, actor_user_id)
        row = await self._expire_stale_ringing_call(tenant_id, row)
        return await self._to_response(tenant_id, row)

    async def create(
        self,
        tenant_id: UUID,
        payload: CallCreate,
        *,
        actor_user_id: UUID,
    ) -> CallResponse:
        require_communication_enabled()
        enforce_call_create_rate_limit(str(actor_user_id))
        settings = get_settings()
        conversation_id = payload.conversation_id
        if conversation_id is None:
            assert payload.user_id is not None
            conv = await self.conversations.create(
                tenant_id,
                ConversationCreate(
                    kind=ConversationKind.DIRECT,
                    other_user_id=payload.user_id,
                ),
                actor_user_id=actor_user_id,
            )
            conversation_id = conv.id
        else:
            await self.conversations.require_participant(
                tenant_id, conversation_id, actor_user_id
            )
        actor_mapping = await self.identity.get_or_create_mapping(
            tenant_id, actor_user_id
        )
        rtc_uid = actor_mapping.rtc_uid
        async with transaction(self.session):
            call_id = uuid4()
            channel = call_channel_name(tenant_id, call_id)
            active_participants = await self.conversations.participants.list_active(
                tenant_id, conversation_id
            )
            scope = (
                CallScope.DIRECT.value
                if len(active_participants) <= 2
                else CallScope.GROUP.value
            )
            invitees = [
                p for p in active_participants if p.user_id != actor_user_id
            ]
            busy_users = await self.repo.users_in_active_calls(
                tenant_id, [actor_user_id, *[invitee.user_id for invitee in invitees]]
            )
            if actor_user_id in busy_users:
                raise ValidationError("You are already in an active call")
            call = await self.repo.create(
                tenant_id,
                {
                    "id": call_id,
                    "conversation_id": conversation_id,
                    "channel_name": channel,
                    "kind": payload.kind.value,
                    "scope": scope,
                    "initiated_by": actor_user_id,
                    "status": CallStatus.RINGING.value,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            await self.participants.add(
                CallParticipant(
                    tenant_id=tenant_id,
                    call_id=call.id,
                    user_id=actor_user_id,
                    rtc_uid=rtc_uid,
                    status=CallParticipantStatus.JOINED.value,
                    joined_at=utcnow(),
                )
            )
            await self.call_events.record(
                tenant_id,
                call.id,
                CallEventType.JOIN,
                user_id=actor_user_id,
            )
            for invitee in invitees:
                invitee_mapping = await self.identity.get_or_create_mapping(
                    tenant_id, invitee.user_id
                )
                is_busy = invitee.user_id in busy_users
                invitee_status = (
                    CallParticipantStatus.BUSY.value
                    if is_busy
                    else CallParticipantStatus.RINGING.value
                )
                await self.participants.add(
                    CallParticipant(
                        tenant_id=tenant_id,
                        call_id=call.id,
                        user_id=invitee.user_id,
                        rtc_uid=invitee_mapping.rtc_uid,
                        status=invitee_status,
                    )
                )
                await self.call_events.record(
                    tenant_id,
                    call.id,
                    CallEventType.RING,
                    user_id=invitee.user_id,
                    payload={"busy": True} if is_busy else None,
                )
            await self.outbox.enqueue(
                tenant_id,
                event_type=RING_TIMEOUT_EVENT,
                aggregate_type="call",
                aggregate_id=call.id,
                dedupe_key=f"call-ring-timeout:{call.id}",
                available_at=ring_timeout_available_at(),  # type: ignore[arg-type]
            )
            caller_name = await self._caller_display_name(tenant_id, actor_user_id)
            is_video = payload.kind == CallKind.VIDEO
            ring_timeout_seconds = settings.call_ring_timeout_seconds
            for invitee in invitees:
                if invitee.user_id in busy_users:
                    continue
                schedule_signaling_event(
                    self.session,
                    build_event(
                        event_type="call.invited",
                        tenant_id=tenant_id,
                        actor_id=actor_user_id,
                        conversation_id=conversation_id,
                        data={
                            "call_id": str(call.id),
                            "kind": payload.kind.value,
                            "channel_name": channel,
                            "scope": scope,
                            "caller_name": caller_name,
                            "ring_timeout_seconds": ring_timeout_seconds,
                            "target_user_id": str(invitee.user_id),
                        },
                    ),
                )
                await self.notifications.notify_incoming_call(
                    tenant_id,
                    user_id=invitee.user_id,
                    call_id=call.id,
                    caller_name=caller_name,
                    is_video=is_video,
                )
        await flush_pending_signaling(self.session)
        token, expires = build_rtc_token(settings, channel=channel, uid=rtc_uid)
        response = await self._to_response(tenant_id, call)
        response.rtc_token = token or None
        response.rtc_uid = rtc_uid
        response.token_expires_at = expires
        return response

    async def accept(
        self, tenant_id: UUID, call_id: UUID, *, actor_user_id: UUID
    ) -> CallResponse:
        return await self._join_or_accept(
            tenant_id, call_id, actor_user_id=actor_user_id, accept=True
        )

    async def reject(
        self, tenant_id: UUID, call_id: UUID, *, actor_user_id: UUID
    ) -> CallResponse:
        require_communication_enabled()
        async with transaction(self.session):
            call, part = await self._require_participant(tenant_id, call_id, actor_user_id)
            transition_participant_status(part.status, CallParticipantStatus.REJECTED.value)
            await self.participants.update(
                part, {"status": CallParticipantStatus.REJECTED.value}
            )
            await self.call_events.record(
                tenant_id,
                call_id,
                CallEventType.REJECT,
                user_id=actor_user_id,
            )
            await self._maybe_finalize_call(tenant_id, call)
            await self._schedule_call_inbox_events(
                event_type="call.rejected",
                tenant_id=tenant_id,
                call=call,
                actor_id=actor_user_id,
            )
        await flush_pending_signaling(self.session)
        return await self._to_response(tenant_id, call)

    async def join(
        self, tenant_id: UUID, call_id: UUID, *, actor_user_id: UUID
    ) -> CallResponse:
        return await self._join_or_accept(
            tenant_id, call_id, actor_user_id=actor_user_id, accept=False
        )

    async def leave(
        self, tenant_id: UUID, call_id: UUID, *, actor_user_id: UUID
    ) -> CallResponse:
        require_communication_enabled()
        async with transaction(self.session):
            call, part = await self._require_participant(tenant_id, call_id, actor_user_id)
            if (
                call.initiated_by == actor_user_id
                and call.status == CallStatus.RINGING.value
            ):
                if part.status == CallParticipantStatus.JOINED.value:
                    transition_participant_status(part.status, CallParticipantStatus.LEFT.value)
                    await self.participants.update(
                        part,
                        {"status": CallParticipantStatus.LEFT.value, "left_at": utcnow()},
                    )
                await self._finalize_call(
                    tenant_id, call, reason="cancelled", actor_user_id=actor_user_id
                )
                await self._schedule_call_inbox_events(
                    event_type="call.ended",
                    tenant_id=tenant_id,
                    call=call,
                    actor_id=actor_user_id,
                )
            elif call.status in (
                CallStatus.ENDED.value,
                CallStatus.CANCELLED.value,
                CallStatus.MISSED.value,
                CallStatus.REJECTED.value,
            ):
                await self._schedule_call_inbox_events(
                    event_type="call.ended",
                    tenant_id=tenant_id,
                    call=call,
                    actor_id=actor_user_id,
                )
            elif (
                call.scope == CallScope.DIRECT.value
                and call.status == CallStatus.ACTIVE.value
            ):
                if part.status == CallParticipantStatus.JOINED.value:
                    transition_participant_status(part.status, CallParticipantStatus.LEFT.value)
                    await self.participants.update(
                        part,
                        {"status": CallParticipantStatus.LEFT.value, "left_at": utcnow()},
                    )
                    await self.call_events.record(
                        tenant_id,
                        call_id,
                        CallEventType.LEAVE,
                        user_id=actor_user_id,
                    )
                await self._finalize_call(
                    tenant_id, call, reason="ended", actor_user_id=actor_user_id
                )
                await self._schedule_call_inbox_events(
                    event_type="call.ended",
                    tenant_id=tenant_id,
                    call=call,
                    actor_id=actor_user_id,
                )
            else:
                if part.status == CallParticipantStatus.JOINED.value:
                    transition_participant_status(part.status, CallParticipantStatus.LEFT.value)
                    await self.participants.update(
                        part,
                        {"status": CallParticipantStatus.LEFT.value, "left_at": utcnow()},
                    )
                    await self.call_events.record(
                        tenant_id,
                        call_id,
                        CallEventType.LEAVE,
                        user_id=actor_user_id,
                    )
                await self._maybe_end_call(tenant_id, call, actor_user_id=actor_user_id)
                schedule_signaling_event(
                    self.session,
                    build_event(
                        event_type="call.participant_left",
                        tenant_id=tenant_id,
                        actor_id=actor_user_id,
                        conversation_id=call.conversation_id,
                        data={"call_id": str(call_id)},
                    ),
                )
        await flush_pending_signaling(self.session)
        return await self._to_response(tenant_id, call)

    async def end(
        self, tenant_id: UUID, call_id: UUID, *, actor_user_id: UUID
    ) -> CallResponse:
        require_communication_enabled()
        async with transaction(self.session):
            call = await self.repo.get(tenant_id, call_id)
            if call is None:
                raise ResourceNotFoundError("Call not found")
            if call.initiated_by != actor_user_id:
                raise PermissionDeniedError()
            await self._finalize_call(
                tenant_id, call, reason="ended", actor_user_id=actor_user_id
            )
            await self._schedule_call_inbox_events(
                event_type="call.ended",
                tenant_id=tenant_id,
                call=call,
                actor_id=actor_user_id,
            )
        await flush_pending_signaling(self.session)
        return await self._to_response(tenant_id, call)

    async def update_media(
        self,
        tenant_id: UUID,
        call_id: UUID,
        payload: CallMediaUpdate,
        *,
        actor_user_id: UUID,
    ) -> CallResponse:
        require_communication_enabled()
        async with transaction(self.session):
            call, part = await self._require_participant(tenant_id, call_id, actor_user_id)
            values = payload.model_dump(exclude_unset=True)
            if values:
                await self.participants.update(part, values)
            schedule_signaling_event(
                self.session,
                build_event(
                    event_type="call.media_changed",
                    tenant_id=tenant_id,
                    actor_id=actor_user_id,
                    conversation_id=call.conversation_id,
                    data={"call_id": str(call_id), **values},
                ),
            )
        await flush_pending_signaling(self.session)
        return await self._to_response(tenant_id, call)

    async def refresh_token(
        self, tenant_id: UUID, call_id: UUID, *, actor_user_id: UUID
    ) -> CallResponse:
        require_communication_enabled()
        enforce_token_rate_limit(str(actor_user_id))
        settings = get_settings()
        call, part = await self._require_participant(tenant_id, call_id, actor_user_id)
        if part.status != CallParticipantStatus.JOINED.value:
            raise ValidationError("Must be joined to refresh token")
        token, expires = build_rtc_token(
            settings, channel=call.channel_name, uid=part.rtc_uid
        )
        response = await self._to_response(tenant_id, call)
        response.rtc_token = token or None
        response.rtc_uid = part.rtc_uid
        response.token_expires_at = expires
        return response

    async def _join_or_accept(
        self,
        tenant_id: UUID,
        call_id: UUID,
        *,
        actor_user_id: UUID,
        accept: bool,
    ) -> CallResponse:
        require_communication_enabled()
        settings = get_settings()
        async with transaction(self.session):
            call = await self.repo.get_for_update(tenant_id, call_id)
            if call is None:
                raise ResourceNotFoundError("Call not found")
            part = await self.participants.get(tenant_id, call_id, actor_user_id)
            if part is None:
                raise ResourceNotFoundError("Call not found")
            already_joined = (
                part.status == CallParticipantStatus.JOINED.value
                and call.status
                in (CallStatus.RINGING.value, CallStatus.ACTIVE.value)
            )
            if not already_joined and call.status == CallStatus.RINGING.value:
                transition_participant_status(part.status, CallParticipantStatus.JOINED.value)
                await self.participants.update(
                    part,
                    {"status": CallParticipantStatus.JOINED.value, "joined_at": utcnow()},
                )
                transition_call_status(call.status, CallStatus.ACTIVE.value)
                await self.repo.update(
                    tenant_id,
                    call_id,
                    {"status": CallStatus.ACTIVE.value, "answered_at": utcnow()},
                )
                await self.call_events.record(
                    tenant_id,
                    call_id,
                    CallEventType.ACCEPT if accept else CallEventType.JOIN,
                    user_id=actor_user_id,
                )
                event_type = "call.accepted" if accept else "call.participant_joined"
            elif not already_joined and call.status == CallStatus.ACTIVE.value:
                transition_participant_status(part.status, CallParticipantStatus.JOINED.value)
                await self.participants.update(
                    part,
                    {"status": CallParticipantStatus.JOINED.value, "joined_at": utcnow()},
                )
                await self.call_events.record(
                    tenant_id,
                    call_id,
                    CallEventType.JOIN,
                    user_id=actor_user_id,
                )
                event_type = "call.participant_joined"
            elif not already_joined:
                raise ValidationError("Call is not joinable")
            if not already_joined and event_type == "call.accepted":
                await self._schedule_call_inbox_events(
                    event_type=event_type,
                    tenant_id=tenant_id,
                    call=call,
                    actor_id=actor_user_id,
                )
            elif not already_joined:
                schedule_signaling_event(
                    self.session,
                    build_event(
                        event_type=event_type,
                        tenant_id=tenant_id,
                        actor_id=actor_user_id,
                        conversation_id=call.conversation_id,
                        data={"call_id": str(call_id)},
                    ),
                )
        await flush_pending_signaling(self.session)
        part = await self.participants.get(tenant_id, call_id, actor_user_id)
        assert part is not None
        token, expires = build_rtc_token(
            settings, channel=call.channel_name, uid=part.rtc_uid
        )
        response = await self._to_response(tenant_id, call)
        response.rtc_token = token or None
        response.rtc_uid = part.rtc_uid
        response.token_expires_at = expires
        return response

    async def _require_participant(
        self, tenant_id: UUID, call_id: UUID, user_id: UUID
    ) -> tuple[Call, CallParticipant]:
        call = await self.repo.get(tenant_id, call_id)
        if call is None:
            raise ResourceNotFoundError("Call not found")
        part = await self.participants.get(tenant_id, call_id, user_id)
        if part is None:
            raise ResourceNotFoundError("Call not found")
        return call, part

    async def _maybe_finalize_call(self, tenant_id: UUID, call: Call) -> None:
        parts = await self.participants.list_for_call(tenant_id, call.id)
        if call.status != CallStatus.RINGING.value:
            return
        ringing = [p for p in parts if p.status == CallParticipantStatus.RINGING.value]
        joined = [p for p in parts if p.status == CallParticipantStatus.JOINED.value]
        rejected = [p for p in parts if p.status == CallParticipantStatus.REJECTED.value]
        if joined:
            return
        if ringing:
            return
        if rejected and len(rejected) == len(parts) - 1:
            await self._finalize_call(
                tenant_id, call, reason="rejected", actor_user_id=None
            )

    async def _maybe_end_call(
        self, tenant_id: UUID, call: Call, *, actor_user_id: UUID | None = None
    ) -> None:
        if call.status != CallStatus.ACTIVE.value:
            return
        parts = await self.participants.list_for_call(tenant_id, call.id)
        joined = [p for p in parts if p.status == CallParticipantStatus.JOINED.value]
        if not joined:
            await self._finalize_call(
                tenant_id, call, reason="all_left", actor_user_id=actor_user_id
            )

    async def _finalize_call(
        self,
        tenant_id: UUID,
        call: Call,
        *,
        reason: str,
        actor_user_id: UUID | None = None,
    ) -> None:
        if call.status in (
            CallStatus.ENDED.value,
            CallStatus.MISSED.value,
            CallStatus.REJECTED.value,
            CallStatus.CANCELLED.value,
        ):
            return
        ended = utcnow()
        duration = None
        if call.answered_at:
            duration = int((ended - call.answered_at).total_seconds())
        missed = reason == "timeout" or (
            reason == "all_left" and call.answered_at is None
        )
        if reason == "rejected" and call.status == CallStatus.RINGING.value:
            transition_call_status(call.status, CallStatus.REJECTED.value)
            final_status = CallStatus.REJECTED.value
        elif missed and call.status == CallStatus.RINGING.value:
            transition_call_status(call.status, CallStatus.MISSED.value)
            final_status = CallStatus.MISSED.value
        elif call.status == CallStatus.RINGING.value and reason in ("ended", "cancelled"):
            transition_call_status(call.status, CallStatus.CANCELLED.value)
            final_status = CallStatus.CANCELLED.value
        else:
            transition_call_status(call.status, CallStatus.ENDED.value)
            final_status = CallStatus.ENDED.value
        await self.repo.update(
            tenant_id,
            call.id,
            {
                "status": final_status,
                "ended_at": ended,
                "end_reason": reason,
                "duration_seconds": duration,
            },
        )
        call.status = final_status
        call.ended_at = ended
        call.end_reason = reason
        call.duration_seconds = duration
        await self.call_events.record(
            tenant_id,
            call.id,
            CallEventType.END,
            user_id=actor_user_id,
            payload={
                "reason": reason,
                "duration_seconds": duration,
                "missed": missed,
                "status": final_status,
            },
        )
        await self.messages.post_call_event_message(
            tenant_id,
            call.conversation_id,
            call_id=call.id,
            call_kind=call.kind,
            duration_seconds=duration,
            missed=missed or final_status == CallStatus.MISSED.value,
            end_reason=reason,
            actor_user_id=actor_user_id or call.initiated_by,
        )

    async def _expire_stale_ringing_call(self, tenant_id: UUID, call: Call) -> Call:
        settings = get_settings()
        if call.status != CallStatus.RINGING.value:
            return call
        deadline = call.started_at + timedelta(seconds=settings.call_ring_timeout_seconds)
        if utcnow() < deadline:
            return call
        async with transaction(self.session):
            current = await self.repo.get(tenant_id, call.id)
            if current is None or current.status != CallStatus.RINGING.value:
                return current or call
            ringing_parts = []
            for part in await self.participants.list_for_call(tenant_id, call.id):
                if part.status == CallParticipantStatus.RINGING.value:
                    transition_participant_status(part.status, CallParticipantStatus.MISSED.value)
                    await self.participants.update(
                        part, {"status": CallParticipantStatus.MISSED.value}
                    )
                    ringing_parts.append(part)
            caller_name = "Someone"
            if current.initiated_by is not None:
                caller_name = await self._caller_display_name(
                    tenant_id, current.initiated_by
                )
            is_video = current.kind == CallKind.VIDEO.value
            for part in ringing_parts:
                await self.notifications.notify_missed_call(
                    tenant_id,
                    user_id=part.user_id,
                    call_id=current.id,
                    caller_name=caller_name,
                    is_video=is_video,
                )
            await self._schedule_call_inbox_events(
                event_type="call.missed",
                tenant_id=tenant_id,
                call=current,
                actor_id=None,
            )
            await self._finalize_call(
                tenant_id, current, reason="timeout", actor_user_id=None
            )
            call = current
        await flush_pending_signaling(self.session)
        refreshed = await self.repo.get(tenant_id, call.id)
        return refreshed or call

    async def _schedule_call_inbox_events(
        self,
        *,
        event_type: str,
        tenant_id: UUID,
        call: Call,
        actor_id: UUID | None,
        data: dict | None = None,
    ) -> None:
        payload = {"call_id": str(call.id), **(data or {})}
        parts = await self.participants.list_for_call(tenant_id, call.id)
        for part in parts:
            schedule_signaling_event(
                self.session,
                build_event(
                    event_type=event_type,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    conversation_id=call.conversation_id,
                    data={**payload, "target_user_id": str(part.user_id)},
                ),
            )

    async def _caller_display_name(self, tenant_id: UUID, user_id: UUID) -> str:
        from sqlalchemy import select

        from app.auth.models import User

        stmt = select(User.name).where(User.tenant_id == tenant_id, User.id == user_id)
        result = await self.session.execute(stmt)
        name = result.scalar_one_or_none()
        return name or "Someone"

    async def _to_response(self, tenant_id: UUID, call: Call) -> CallResponse:
        parts = await self.participants.list_for_call(tenant_id, call.id)
        response = CallResponse.model_validate(call)
        response.participants = [
            CallParticipantResponse.model_validate(p) for p in parts
        ]
        return response

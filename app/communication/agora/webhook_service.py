"""Agora RTC webhook processing."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.utils.datetime import utcnow
from app.communication.calls.events import CallEventService
from app.communication.calls.repository import CallParticipantRepository, CallRepository
from app.communication.calls.state import transition_participant_status
from app.communication.shared.signaling_publisher import flush_pending_signaling
from app.core.enums import CallEventType, CallParticipantStatus
from app.db.session import transaction

_JOIN_EVENT_TYPES = frozenset({103, 105, 107})
_LEAVE_EVENT_TYPES = frozenset({104, 106, 108})


class AgoraWebhookService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.calls = CallRepository(session)
        self.participants = CallParticipantRepository(session)
        self.events = CallEventService(session)

    async def process(self, payload: dict) -> bool:
        event_type = payload.get("eventType")
        if event_type not in _JOIN_EVENT_TYPES | _LEAVE_EVENT_TYPES:
            return False
        notice_id = payload.get("noticeId")
        if not isinstance(notice_id, str) or not notice_id:
            return False
        event_payload = payload.get("payload")
        if not isinstance(event_payload, dict):
            return False
        channel_name = event_payload.get("channelName")
        if not isinstance(channel_name, str) or not channel_name:
            return False
        call = await self.calls.get_by_channel_name(channel_name)
        if call is None:
            return False
        rtc_uid = event_payload.get("uid")
        user_id: UUID | None = None
        if isinstance(rtc_uid, int):
            part = await self.participants.get_by_rtc_uid(
                call.tenant_id, call.id, rtc_uid
            )
            if part is not None:
                user_id = part.user_id
        call_event_type = (
            CallEventType.JOIN
            if event_type in _JOIN_EVENT_TYPES
            else CallEventType.LEAVE
        )
        stored = await self.events.record_webhook(
            call.tenant_id,
            call.id,
            call_event_type,
            notice_id=notice_id,
            user_id=user_id,
            payload={
                "agora_event_type": event_type,
                "channel_name": channel_name,
                "rtc_uid": rtc_uid,
                "reason": event_payload.get("reason"),
                "duration": event_payload.get("duration"),
            },
        )
        if stored is None:
            return False

        if event_type in _LEAVE_EVENT_TYPES and user_id is not None:
            async with transaction(self.session):
                part = await self.participants.get(call.tenant_id, call.id, user_id)
                if part is not None and part.status == CallParticipantStatus.JOINED.value:
                    transition_participant_status(
                        part.status, CallParticipantStatus.LEFT.value
                    )
                    await self.participants.update(
                        part,
                        {
                            "status": CallParticipantStatus.LEFT.value,
                            "left_at": utcnow(),
                        },
                    )
                    from app.communication.calls.service import CallService

                    call_service = CallService(self.session)
                    refreshed = await self.calls.get(call.tenant_id, call.id)
                    if refreshed is not None:
                        await call_service._maybe_end_call(
                            call.tenant_id, refreshed, actor_user_id=user_id
                        )
            await flush_pending_signaling(self.session)

        return True

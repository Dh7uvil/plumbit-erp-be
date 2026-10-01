"""Outbox handlers for call lifecycle."""

from __future__ import annotations

from datetime import timedelta

from app.common.outbox.models import OutboxEvent
from app.common.utils.datetime import utcnow
from app.communication.calls.repository import CallParticipantRepository, CallRepository
from app.communication.calls.state import transition_participant_status
from app.communication.shared.notifications import CommunicationNotificationService
from app.communication.shared.signaling_publisher import flush_pending_signaling
from app.core.config import get_settings
from app.core.enums import CallKind, CallParticipantStatus, CallStatus
from app.db.session import async_session_factory, transaction

RING_TIMEOUT_EVENT = "communication.call.ring_timeout"


async def handle_call_ring_timeout(event: OutboxEvent) -> None:
    settings = get_settings()
    if not settings.feature_communication_enabled:
        return
    call_id = event.aggregate_id
    tenant_id = event.tenant_id
    async with async_session_factory() as session:
        async with transaction(session):
            calls = CallRepository(session)
            participants = CallParticipantRepository(session)
            call = await calls.get(tenant_id, call_id)
            if call is None or call.status != CallStatus.RINGING.value:
                return
            ringing_parts = []
            for part in await participants.list_for_call(tenant_id, call_id):
                if part.status == CallParticipantStatus.RINGING.value:
                    transition_participant_status(part.status, CallParticipantStatus.MISSED.value)
                    await participants.update(
                        part, {"status": CallParticipantStatus.MISSED.value}
                    )
                    ringing_parts.append(part)
            caller_name = "Someone"
            if call.initiated_by is not None:
                from sqlalchemy import select

                from app.auth.models import User

                stmt = select(User.name).where(
                    User.tenant_id == tenant_id, User.id == call.initiated_by
                )
                result = await session.execute(stmt)
                caller_name = result.scalar_one_or_none() or caller_name
            notifications = CommunicationNotificationService(session)
            is_video = call.kind == CallKind.VIDEO.value
            for part in ringing_parts:
                await notifications.notify_missed_call(
                    tenant_id,
                    user_id=part.user_id,
                    call_id=call_id,
                    caller_name=caller_name,
                    is_video=is_video,
                )
            from app.communication.calls.service import CallService

            call_service = CallService(session)
            await call_service._schedule_call_inbox_events(
                event_type="call.missed",
                tenant_id=tenant_id,
                call=call,
                actor_id=None,
            )
            await call_service._finalize_call(
                tenant_id, call, reason="timeout", actor_user_id=None
            )
        await flush_pending_signaling(session)


def ring_timeout_available_at():
    settings = get_settings()
    return utcnow() + timedelta(seconds=settings.call_ring_timeout_seconds)

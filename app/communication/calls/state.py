"""Call state machine transitions."""

from __future__ import annotations

from app.core.enums import CallParticipantStatus, CallStatus
from app.core.exceptions import InvalidStatusTransitionError

_CALL_TRANSITIONS: dict[str, frozenset[str]] = {
    CallStatus.RINGING.value: frozenset(
        {CallStatus.ACTIVE.value, CallStatus.REJECTED.value, CallStatus.MISSED.value, CallStatus.CANCELLED.value}
    ),
    CallStatus.ACTIVE.value: frozenset({CallStatus.ENDED.value}),
}

_PARTICIPANT_TRANSITIONS: dict[str, frozenset[str]] = {
    CallParticipantStatus.RINGING.value: frozenset(
        {
            CallParticipantStatus.JOINED.value,
            CallParticipantStatus.REJECTED.value,
            CallParticipantStatus.MISSED.value,
            CallParticipantStatus.BUSY.value,
        }
    ),
    CallParticipantStatus.JOINED.value: frozenset({CallParticipantStatus.LEFT.value}),
    CallParticipantStatus.BUSY.value: frozenset(
        {
            CallParticipantStatus.JOINED.value,
            CallParticipantStatus.MISSED.value,
            CallParticipantStatus.REJECTED.value,
            CallParticipantStatus.LEFT.value,
        }
    ),
}


def transition_call_status(current: str, new: str) -> None:
    allowed = _CALL_TRANSITIONS.get(current, frozenset())
    if new not in allowed:
        raise InvalidStatusTransitionError(
            f"Cannot transition call from {current} to {new}",
            details={"current": current, "target": new},
        )


def transition_participant_status(current: str, new: str) -> None:
    allowed = _PARTICIPANT_TRANSITIONS.get(current, frozenset())
    if new not in allowed:
        raise InvalidStatusTransitionError(
            f"Cannot transition participant from {current} to {new}",
            details={"current": current, "target": new},
        )

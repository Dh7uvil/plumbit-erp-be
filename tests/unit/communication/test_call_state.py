"""Call state machine tests."""

import pytest

from app.communication.calls.state import transition_call_status, transition_participant_status
from app.core.enums import CallParticipantStatus, CallStatus
from app.core.exceptions import InvalidStatusTransitionError


def test_valid_call_transitions() -> None:
    transition_call_status(CallStatus.RINGING.value, CallStatus.ACTIVE.value)
    transition_call_status(CallStatus.ACTIVE.value, CallStatus.ENDED.value)


def test_invalid_call_transition() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        transition_call_status(CallStatus.ENDED.value, CallStatus.ACTIVE.value)


def test_participant_transitions() -> None:
    transition_participant_status(
        CallParticipantStatus.RINGING.value, CallParticipantStatus.JOINED.value
    )

"""Unit tests for activity workflow."""

import pytest

from app.core.enums import ActivityStatus
from app.core.exceptions import InvalidStatusTransitionError
from app.crm.activities.workflow import (
    assert_complete_allowed,
    assert_editable,
    available_actions,
)


def test_open_activity_is_editable() -> None:
    assert_editable(ActivityStatus.OPEN)


def test_completed_activity_is_not_editable() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        assert_editable(ActivityStatus.COMPLETED)


def test_cancelled_activity_cannot_be_completed() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        assert_complete_allowed(ActivityStatus.CANCELLED)


def test_available_actions_match_open_state_machine() -> None:
    assert available_actions(ActivityStatus.OPEN, can_update=True, can_delete=True) == [
        "update",
        "complete",
        "delete",
    ]
    assert available_actions(ActivityStatus.COMPLETED, can_update=True, can_delete=True) == []
    assert available_actions(ActivityStatus.OPEN, can_update=False, can_delete=True) == ["delete"]

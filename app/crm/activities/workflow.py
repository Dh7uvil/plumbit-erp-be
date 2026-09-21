"""Activity status rules."""

from app.core.enums import ActivityStatus
from app.core.exceptions import InvalidStatusTransitionError


def assert_editable(status: ActivityStatus) -> None:
    if status is not ActivityStatus.OPEN:
        raise InvalidStatusTransitionError(f"Activities in {status.value} status cannot be changed")


def assert_complete_allowed(status: ActivityStatus) -> None:
    if status is not ActivityStatus.OPEN:
        raise InvalidStatusTransitionError("Only open activities can be completed")


def available_actions(status: ActivityStatus, *, can_update: bool, can_delete: bool) -> list[str]:
    if status is not ActivityStatus.OPEN:
        return []
    actions: list[str] = []
    if can_update:
        actions.extend(["update", "complete"])
    if can_delete:
        actions.append("delete")
    return actions

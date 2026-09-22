"""Cost sheet status machine."""

from app.core.enums import CostSheetStatus
from app.core.exceptions import InvalidStatusTransitionError

_TRANSITIONS: dict[tuple[CostSheetStatus, str], CostSheetStatus] = {
    (CostSheetStatus.DRAFT, "confirm"): CostSheetStatus.CONFIRMED,
    (CostSheetStatus.CONFIRMED, "close"): CostSheetStatus.CLOSED,
    (CostSheetStatus.CONFIRMED, "reopen"): CostSheetStatus.DRAFT,
}

_EDITABLE = frozenset({CostSheetStatus.DRAFT})


def next_status(current: CostSheetStatus, action: str) -> CostSheetStatus:
    target = _TRANSITIONS.get((current, action))
    if target is None:
        raise InvalidStatusTransitionError(
            f"Cannot {action} a cost sheet in {current.value} status"
        )
    return target


def transition_actions(current: CostSheetStatus) -> list[str]:
    return [action for (status, action) in _TRANSITIONS if status == current and action != "delete"]


def assert_editable(status: CostSheetStatus) -> None:
    if status not in _EDITABLE:
        raise InvalidStatusTransitionError("Only draft cost sheets can be edited")

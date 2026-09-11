"""Shipment tracking-state machine. Not a post workflow."""

from app.core.enums import ShipmentStatus
from app.core.exceptions import InvalidStatusTransitionError

_TRANSITIONS: dict[tuple[ShipmentStatus, str], ShipmentStatus] = {
    (ShipmentStatus.DRAFT, "dispatch"): ShipmentStatus.DISPATCHED,
    (ShipmentStatus.DRAFT, "cancel"): ShipmentStatus.CANCELLED,
    (ShipmentStatus.DISPATCHED, "arrive"): ShipmentStatus.ARRIVED,
    (ShipmentStatus.DISPATCHED, "cancel"): ShipmentStatus.CANCELLED,
    (ShipmentStatus.IN_TRANSIT, "arrive"): ShipmentStatus.ARRIVED,
    (ShipmentStatus.IN_TRANSIT, "cancel"): ShipmentStatus.CANCELLED,
    (ShipmentStatus.ARRIVED, "close"): ShipmentStatus.CLOSED,
}

_EDITABLE = frozenset({ShipmentStatus.DRAFT})
_TRACKABLE = frozenset(
    {ShipmentStatus.DISPATCHED, ShipmentStatus.IN_TRANSIT, ShipmentStatus.ARRIVED}
)


def next_status(current: ShipmentStatus, action: str) -> ShipmentStatus:
    target = _TRANSITIONS.get((current, action))
    if target is None:
        raise InvalidStatusTransitionError(f"Cannot {action} a shipment in {current.value} status")
    return target


def transition_actions(current: ShipmentStatus) -> list[str]:
    return [action for (status, action) in _TRANSITIONS if status == current]


def assert_editable(status: ShipmentStatus) -> None:
    if status not in _EDITABLE:
        raise InvalidStatusTransitionError("Only draft shipments can be edited")


def assert_trackable(status: ShipmentStatus) -> None:
    if status not in _TRACKABLE:
        raise InvalidStatusTransitionError("Tracking can only be updated after dispatch")

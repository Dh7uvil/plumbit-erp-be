"""Package status machine."""

from app.core.enums import PackageStatus
from app.core.exceptions import InvalidStatusTransitionError

_TRANSITIONS: dict[tuple[PackageStatus, str], PackageStatus] = {
    (PackageStatus.DRAFT, "pack"): PackageStatus.PACKED,
    (PackageStatus.DRAFT, "cancel"): PackageStatus.CANCELLED,
    (PackageStatus.PACKED, "cancel"): PackageStatus.CANCELLED,
}

_EDITABLE = frozenset({PackageStatus.DRAFT})


def next_status(current: PackageStatus, action: str) -> PackageStatus:
    target = _TRANSITIONS.get((current, action))
    if target is None:
        raise InvalidStatusTransitionError(f"Cannot {action} a package in {current.value} status")
    return target


def transition_actions(current: PackageStatus) -> list[str]:
    return [action for (status, action) in _TRANSITIONS if status == current]


def assert_editable(status: PackageStatus) -> None:
    if status not in _EDITABLE:
        raise InvalidStatusTransitionError("Only draft packages can be edited")

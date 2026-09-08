"""Sales order status machine."""

from app.core.enums import SalesOrderStatus
from app.core.exceptions import InvalidStatusTransitionError

_TRANSITIONS: dict[tuple[SalesOrderStatus, str], SalesOrderStatus] = {
    (SalesOrderStatus.DRAFT, "submit"): SalesOrderStatus.PENDING_APPROVAL,
    (SalesOrderStatus.DRAFT, "confirm"): SalesOrderStatus.CONFIRMED,
    (SalesOrderStatus.DRAFT, "cancel"): SalesOrderStatus.CANCELLED,
    (SalesOrderStatus.PENDING_APPROVAL, "approve"): SalesOrderStatus.APPROVED,
    (SalesOrderStatus.PENDING_APPROVAL, "reject"): SalesOrderStatus.REJECTED,
    (SalesOrderStatus.PENDING_APPROVAL, "cancel"): SalesOrderStatus.CANCELLED,
    (SalesOrderStatus.REJECTED, "reopen"): SalesOrderStatus.DRAFT,
    (SalesOrderStatus.REJECTED, "cancel"): SalesOrderStatus.CANCELLED,
    (SalesOrderStatus.APPROVED, "confirm"): SalesOrderStatus.CONFIRMED,
    (SalesOrderStatus.APPROVED, "cancel"): SalesOrderStatus.CANCELLED,
    (SalesOrderStatus.CONFIRMED, "close"): SalesOrderStatus.CLOSED,
    (SalesOrderStatus.CONFIRMED, "cancel"): SalesOrderStatus.CANCELLED,
    (SalesOrderStatus.CLOSED, "reopen"): SalesOrderStatus.CONFIRMED,
}

_EDITABLE = frozenset({SalesOrderStatus.DRAFT})


def next_status(current: SalesOrderStatus, action: str) -> SalesOrderStatus:
    target = _TRANSITIONS.get((current, action))
    if target is None:
        raise InvalidStatusTransitionError(
            f"Cannot {action} a sales order in {current.value} status"
        )
    return target


def transition_actions(current: SalesOrderStatus) -> list[str]:
    """Return machine actions available from `current`, in definition order."""

    return [action for (status, action) in _TRANSITIONS if status == current]


def assert_editable(status: SalesOrderStatus) -> None:
    if status not in _EDITABLE:
        raise InvalidStatusTransitionError("Only draft sales orders can be edited")

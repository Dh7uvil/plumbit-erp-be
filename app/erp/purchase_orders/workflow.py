"""Purchase order status machine."""

from app.core.enums import PurchaseOrderStatus
from app.core.exceptions import InvalidStatusTransitionError

_TRANSITIONS: dict[tuple[PurchaseOrderStatus, str], PurchaseOrderStatus] = {
    (PurchaseOrderStatus.DRAFT, "submit"): PurchaseOrderStatus.PENDING_APPROVAL,
    (PurchaseOrderStatus.DRAFT, "issue"): PurchaseOrderStatus.ISSUED,
    (PurchaseOrderStatus.DRAFT, "cancel"): PurchaseOrderStatus.CANCELLED,
    (PurchaseOrderStatus.PENDING_APPROVAL, "approve"): PurchaseOrderStatus.APPROVED,
    (PurchaseOrderStatus.PENDING_APPROVAL, "reject"): PurchaseOrderStatus.REJECTED,
    (PurchaseOrderStatus.PENDING_APPROVAL, "cancel"): PurchaseOrderStatus.CANCELLED,
    (PurchaseOrderStatus.REJECTED, "reopen"): PurchaseOrderStatus.DRAFT,
    (PurchaseOrderStatus.REJECTED, "cancel"): PurchaseOrderStatus.CANCELLED,
    (PurchaseOrderStatus.APPROVED, "issue"): PurchaseOrderStatus.ISSUED,
    (PurchaseOrderStatus.APPROVED, "cancel"): PurchaseOrderStatus.CANCELLED,
    (PurchaseOrderStatus.ISSUED, "close"): PurchaseOrderStatus.CLOSED,
    (PurchaseOrderStatus.ISSUED, "cancel"): PurchaseOrderStatus.CANCELLED,
    (PurchaseOrderStatus.CLOSED, "reopen"): PurchaseOrderStatus.ISSUED,
}

_EDITABLE = frozenset({PurchaseOrderStatus.DRAFT})


def next_status(current: PurchaseOrderStatus, action: str) -> PurchaseOrderStatus:
    target = _TRANSITIONS.get((current, action))
    if target is None:
        raise InvalidStatusTransitionError(
            f"Cannot {action} a purchase order in {current.value} status"
        )
    return target


def transition_actions(current: PurchaseOrderStatus) -> list[str]:
    """Return machine actions available from `current`, in definition order."""

    return [action for (status, action) in _TRANSITIONS if status == current]


def assert_editable(status: PurchaseOrderStatus) -> None:
    if status not in _EDITABLE:
        raise InvalidStatusTransitionError("Only draft purchase orders can be edited")

"""Quality inspection qty rules."""

from decimal import Decimal

from app.core.enums import QcDisposition, QualityInspectionStatus
from app.core.exceptions import (
    InvalidStatusTransitionError,
    QualityQtyMismatchError,
    ValidationError,
)

_ZERO = Decimal("0")

_TRANSITIONS: dict[tuple[QualityInspectionStatus, str], QualityInspectionStatus] = {
    (QualityInspectionStatus.DRAFT, "approve"): QualityInspectionStatus.APPROVED,
    (QualityInspectionStatus.DRAFT, "cancel"): QualityInspectionStatus.CANCELLED,
}

_EDITABLE = frozenset({QualityInspectionStatus.DRAFT})


def next_status(current: QualityInspectionStatus, action: str) -> QualityInspectionStatus:
    target = _TRANSITIONS.get((current, action))
    if target is None:
        raise InvalidStatusTransitionError(
            f"Cannot {action} a quality inspection in {current.value} status"
        )
    return target


def transition_actions(current: QualityInspectionStatus) -> list[str]:
    return [action for (status, action) in _TRANSITIONS if status == current]


def assert_editable(status: QualityInspectionStatus) -> None:
    if status not in _EDITABLE:
        raise InvalidStatusTransitionError("Only draft quality inspections can be edited")


def assert_line_quantities(
    *,
    qty_inspected: Decimal,
    qty_accepted: Decimal,
    qty_rejected: Decimal,
    qty_rework: Decimal,
    remaining_hold: Decimal,
    disposition: QcDisposition | None,
) -> None:
    if qty_inspected < _ZERO or qty_accepted < _ZERO or qty_rejected < _ZERO or qty_rework < _ZERO:
        raise QualityQtyMismatchError("Inspection quantities cannot be negative")
    if qty_accepted + qty_rejected + qty_rework != qty_inspected:
        raise QualityQtyMismatchError(
            "Accepted, rejected and rework quantities must sum to inspected quantity",
            details={
                "qty_inspected": str(qty_inspected),
                "qty_accepted": str(qty_accepted),
                "qty_rejected": str(qty_rejected),
                "qty_rework": str(qty_rework),
            },
        )
    if qty_inspected > remaining_hold:
        raise QualityQtyMismatchError(
            "Inspected quantity exceeds remaining quality hold on this receipt line",
            details={
                "qty_inspected": str(qty_inspected),
                "remaining_hold": str(remaining_hold),
            },
        )
    if qty_rejected > _ZERO and disposition is None:
        raise ValidationError(
            "A disposition is required when rejected quantity is greater than zero"
        )
    if qty_rejected == _ZERO and disposition is not None:
        raise ValidationError(
            "Disposition can only be set when rejected quantity is greater than zero"
        )

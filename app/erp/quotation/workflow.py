"""Quotation status machine."""

from app.core.enums import QuotationStatus
from app.core.exceptions import InvalidStatusTransitionError

_TRANSITIONS: dict[tuple[QuotationStatus, str], QuotationStatus] = {
    (QuotationStatus.DRAFT, "submit"): QuotationStatus.PENDING_APPROVAL,
    (QuotationStatus.DRAFT, "send"): QuotationStatus.SENT,
    (QuotationStatus.DRAFT, "cancel"): QuotationStatus.CANCELLED,
    (QuotationStatus.PENDING_APPROVAL, "approve"): QuotationStatus.APPROVED,
    (QuotationStatus.PENDING_APPROVAL, "reject"): QuotationStatus.REJECTED,
    (QuotationStatus.PENDING_APPROVAL, "cancel"): QuotationStatus.CANCELLED,
    (QuotationStatus.REJECTED, "reopen"): QuotationStatus.DRAFT,
    (QuotationStatus.REJECTED, "cancel"): QuotationStatus.CANCELLED,
    (QuotationStatus.APPROVED, "send"): QuotationStatus.SENT,
    (QuotationStatus.APPROVED, "cancel"): QuotationStatus.CANCELLED,
    (QuotationStatus.SENT, "accept"): QuotationStatus.ACCEPTED,
    (QuotationStatus.SENT, "decline"): QuotationStatus.DECLINED,
    (QuotationStatus.SENT, "revise"): QuotationStatus.DRAFT,
    (QuotationStatus.SENT, "cancel"): QuotationStatus.CANCELLED,
    (QuotationStatus.EXPIRED, "revise"): QuotationStatus.DRAFT,
    (QuotationStatus.DECLINED, "revise"): QuotationStatus.DRAFT,
    (QuotationStatus.ACCEPTED, "revise"): QuotationStatus.DRAFT,
    (QuotationStatus.ACCEPTED, "cancel"): QuotationStatus.CANCELLED,
    (QuotationStatus.ACCEPTED, "convert"): QuotationStatus.CONVERTED,
}

_EDITABLE = frozenset({QuotationStatus.DRAFT})
_CONVERTIBLE = frozenset({QuotationStatus.ACCEPTED})
_PROFORMA_SOURCE = frozenset({QuotationStatus.SENT, QuotationStatus.ACCEPTED})


def next_status(current: QuotationStatus, action: str) -> QuotationStatus:
    target = _TRANSITIONS.get((current, action))
    if target is None:
        raise InvalidStatusTransitionError(f"Cannot {action} a quotation in {current.value} status")
    return target


def transition_actions(current: QuotationStatus) -> list[str]:
    """Return machine actions available from `current`, in definition order."""

    return [action for (status, action) in _TRANSITIONS if status == current]


def assert_editable(status: QuotationStatus) -> None:
    if status not in _EDITABLE:
        raise InvalidStatusTransitionError("Only draft quotations can be edited")


def assert_convertible(status: QuotationStatus) -> None:
    if status not in _CONVERTIBLE:
        raise InvalidStatusTransitionError(
            "Only an accepted quotation can be converted to a sales order"
        )


def assert_proforma_source(status: QuotationStatus) -> None:
    if status not in _PROFORMA_SOURCE:
        raise InvalidStatusTransitionError(
            "Only a sent or accepted quotation can raise a proforma invoice"
        )

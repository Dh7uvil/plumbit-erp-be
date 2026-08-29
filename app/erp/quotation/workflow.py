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
    (QuotationStatus.SENT, "cancel"): QuotationStatus.CANCELLED,
    (QuotationStatus.ACCEPTED, "cancel"): QuotationStatus.CANCELLED,
}

_EDITABLE = frozenset({QuotationStatus.DRAFT})
_PRE_CONVERT = frozenset(
    {
        QuotationStatus.DRAFT,
        QuotationStatus.PENDING_APPROVAL,
        QuotationStatus.APPROVED,
        QuotationStatus.REJECTED,
        QuotationStatus.SENT,
        QuotationStatus.ACCEPTED,
        QuotationStatus.EXPIRED,
        QuotationStatus.DECLINED,
    }
)


def next_status(current: QuotationStatus, action: str) -> QuotationStatus:
    target = _TRANSITIONS.get((current, action))
    if target is None:
        raise InvalidStatusTransitionError(f"Cannot {action} a quotation in {current.value} status")
    return target


def assert_editable(status: QuotationStatus) -> None:
    if status not in _EDITABLE:
        raise InvalidStatusTransitionError("Only draft quotations can be edited")


def assert_pre_convert(status: QuotationStatus) -> None:
    if status not in _PRE_CONVERT or status == QuotationStatus.CONVERTED:
        raise InvalidStatusTransitionError("Quotation cannot be cancelled in this status")

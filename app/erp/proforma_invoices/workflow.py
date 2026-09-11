"""Proforma invoice status machine."""

from app.core.enums import ProformaInvoiceStatus
from app.core.exceptions import InvalidStatusTransitionError

_TRANSITIONS: dict[tuple[ProformaInvoiceStatus, str], ProformaInvoiceStatus] = {
    (ProformaInvoiceStatus.DRAFT, "send"): ProformaInvoiceStatus.SENT,
    (ProformaInvoiceStatus.DRAFT, "cancel"): ProformaInvoiceStatus.CANCELLED,
    (ProformaInvoiceStatus.SENT, "confirm"): ProformaInvoiceStatus.CONFIRMED,
    (ProformaInvoiceStatus.SENT, "decline"): ProformaInvoiceStatus.DECLINED,
    (ProformaInvoiceStatus.SENT, "revise"): ProformaInvoiceStatus.DRAFT,
    (ProformaInvoiceStatus.SENT, "cancel"): ProformaInvoiceStatus.CANCELLED,
    (ProformaInvoiceStatus.EXPIRED, "revise"): ProformaInvoiceStatus.DRAFT,
    (ProformaInvoiceStatus.EXPIRED, "cancel"): ProformaInvoiceStatus.CANCELLED,
    (ProformaInvoiceStatus.DECLINED, "reopen"): ProformaInvoiceStatus.DRAFT,
    (ProformaInvoiceStatus.DECLINED, "cancel"): ProformaInvoiceStatus.CANCELLED,
    (ProformaInvoiceStatus.CONFIRMED, "convert"): ProformaInvoiceStatus.CONVERTED,
    (ProformaInvoiceStatus.CONFIRMED, "cancel"): ProformaInvoiceStatus.CANCELLED,
    (ProformaInvoiceStatus.PARTIALLY_CONVERTED, "convert"): ProformaInvoiceStatus.CONVERTED,
}

_EDITABLE = frozenset({ProformaInvoiceStatus.DRAFT})
_CONVERTIBLE = frozenset(
    {ProformaInvoiceStatus.CONFIRMED, ProformaInvoiceStatus.PARTIALLY_CONVERTED}
)


def next_status(current: ProformaInvoiceStatus, action: str) -> ProformaInvoiceStatus:
    target = _TRANSITIONS.get((current, action))
    if target is None:
        raise InvalidStatusTransitionError(
            f"Cannot {action} a proforma invoice in {current.value} status"
        )
    return target


def transition_actions(current: ProformaInvoiceStatus) -> list[str]:
    """Return machine actions available from `current`, in definition order."""

    return [action for (status, action) in _TRANSITIONS if status == current]


def assert_editable(status: ProformaInvoiceStatus) -> None:
    if status not in _EDITABLE:
        raise InvalidStatusTransitionError("Only draft proforma invoices can be edited")


def assert_convertible(status: ProformaInvoiceStatus) -> None:
    if status not in _CONVERTIBLE:
        raise InvalidStatusTransitionError(
            "Only a confirmed or partially converted proforma invoice can be converted"
        )

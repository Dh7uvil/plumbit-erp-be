"""Sales invoice status machine."""

from app.core.enums import InvoiceDocumentStatus
from app.core.exceptions import InvalidStatusTransitionError

_TRANSITIONS: dict[tuple[InvoiceDocumentStatus, str], InvoiceDocumentStatus] = {
    (InvoiceDocumentStatus.DRAFT, "post"): InvoiceDocumentStatus.POSTED,
    (InvoiceDocumentStatus.DRAFT, "cancel"): InvoiceDocumentStatus.CANCELLED,
    (InvoiceDocumentStatus.POSTED, "cancel"): InvoiceDocumentStatus.CANCELLED,
}

_EDITABLE = frozenset({InvoiceDocumentStatus.DRAFT})


def next_status(current: InvoiceDocumentStatus, action: str) -> InvoiceDocumentStatus:
    target = _TRANSITIONS.get((current, action))
    if target is None:
        raise InvalidStatusTransitionError(
            f"Cannot {action} a sales invoice in {current.value} status"
        )
    return target


def transition_actions(current: InvoiceDocumentStatus) -> list[str]:
    return [action for (status, action) in _TRANSITIONS if status == current]


def assert_editable(status: InvoiceDocumentStatus) -> None:
    if status not in _EDITABLE:
        raise InvalidStatusTransitionError("Only draft sales invoices can be edited")

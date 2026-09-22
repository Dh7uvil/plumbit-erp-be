"""Cheque status machine."""

from app.core.enums import ChequeStatus
from app.core.exceptions import InvalidStatusTransitionError

_TRANSITIONS: dict[tuple[ChequeStatus, str], ChequeStatus] = {
    (ChequeStatus.DRAFT, "issue"): ChequeStatus.ISSUED,
    (ChequeStatus.DRAFT, "cancel"): ChequeStatus.CANCELLED,
    (ChequeStatus.ISSUED, "deposit"): ChequeStatus.DEPOSITED,
    (ChequeStatus.ISSUED, "clear"): ChequeStatus.CLEARED,
    (ChequeStatus.ISSUED, "bounce"): ChequeStatus.BOUNCED,
    (ChequeStatus.ISSUED, "cancel"): ChequeStatus.CANCELLED,
    (ChequeStatus.DEPOSITED, "clear"): ChequeStatus.CLEARED,
    (ChequeStatus.DEPOSITED, "bounce"): ChequeStatus.BOUNCED,
    (ChequeStatus.CLEARED, "bounce"): ChequeStatus.BOUNCED,
}

_EDITABLE = frozenset({ChequeStatus.DRAFT})


def next_status(current: ChequeStatus, action: str) -> ChequeStatus:
    target = _TRANSITIONS.get((current, action))
    if target is None:
        raise InvalidStatusTransitionError(f"Cannot {action} a cheque in {current.value} status")
    return target


def transition_actions(current: ChequeStatus, *, direction: str) -> list[str]:
    actions = [action for (status, action) in _TRANSITIONS if status == current]
    if direction != "INBOUND" and "deposit" in actions:
        actions.remove("deposit")
    return actions


def assert_editable(status: ChequeStatus) -> None:
    if status not in _EDITABLE:
        raise InvalidStatusTransitionError("Only draft cheques can be edited")

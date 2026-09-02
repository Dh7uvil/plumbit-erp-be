"""Stock adjustment status machine."""

from app.core.enums import StockDocumentStatus
from app.core.exceptions import InvalidStatusTransitionError

_TRANSITIONS: dict[tuple[StockDocumentStatus, str], StockDocumentStatus] = {
    (StockDocumentStatus.DRAFT, "post"): StockDocumentStatus.POSTED,
    (StockDocumentStatus.DRAFT, "cancel"): StockDocumentStatus.CANCELLED,
}

_EDITABLE = frozenset({StockDocumentStatus.DRAFT})


def next_status(current: StockDocumentStatus, action: str) -> StockDocumentStatus:
    target = _TRANSITIONS.get((current, action))
    if target is None:
        raise InvalidStatusTransitionError(
            f"Cannot {action} a stock adjustment in {current.value} status"
        )
    return target


def transition_actions(current: StockDocumentStatus) -> list[str]:
    return [action for (status, action) in _TRANSITIONS if status == current]


def assert_editable(status: StockDocumentStatus) -> None:
    if status not in _EDITABLE:
        raise InvalidStatusTransitionError("Only draft stock adjustments can be edited")

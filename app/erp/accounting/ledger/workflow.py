"""Journal entry status machine."""

from app.core.enums import JournalEntryStatus
from app.core.exceptions import InvalidStatusTransitionError

_TRANSITIONS: dict[tuple[JournalEntryStatus, str], JournalEntryStatus] = {
    (JournalEntryStatus.DRAFT, "post"): JournalEntryStatus.POSTED,
    (JournalEntryStatus.DRAFT, "cancel"): JournalEntryStatus.CANCELLED,
}

_EDITABLE = frozenset({JournalEntryStatus.DRAFT})


def next_status(current: JournalEntryStatus, action: str) -> JournalEntryStatus:
    target = _TRANSITIONS.get((current, action))
    if target is None:
        raise InvalidStatusTransitionError(
            f"Cannot {action} a journal entry in {current.value} status"
        )
    return target


def transition_actions(current: JournalEntryStatus) -> list[str]:
    actions = [action for (status, action) in _TRANSITIONS if status == current]
    if current == JournalEntryStatus.POSTED:
        actions.append("reverse")
    return actions


def assert_editable(status: JournalEntryStatus) -> None:
    if status not in _EDITABLE:
        raise InvalidStatusTransitionError("Only draft journal entries can be edited")

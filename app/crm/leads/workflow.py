"""Lead status rules."""

from app.core.enums import LeadStatus
from app.core.exceptions import InvalidStatusTransitionError, ValidationError

_TERMINAL = frozenset({LeadStatus.CONVERTED, LeadStatus.LOST})

_ALLOWED: dict[LeadStatus, frozenset[LeadStatus]] = {
    LeadStatus.NEW: frozenset(
        {LeadStatus.CONTACTED, LeadStatus.QUALIFIED, LeadStatus.UNQUALIFIED, LeadStatus.LOST}
    ),
    LeadStatus.CONTACTED: frozenset(
        {
            LeadStatus.NEW,
            LeadStatus.QUALIFIED,
            LeadStatus.UNQUALIFIED,
            LeadStatus.LOST,
        }
    ),
    LeadStatus.QUALIFIED: frozenset(
        {LeadStatus.CONTACTED, LeadStatus.UNQUALIFIED, LeadStatus.LOST}
    ),
    LeadStatus.UNQUALIFIED: frozenset({LeadStatus.NEW, LeadStatus.CONTACTED, LeadStatus.LOST}),
    LeadStatus.LOST: frozenset(),
    LeadStatus.CONVERTED: frozenset(),
}


def assert_editable(status: LeadStatus) -> None:
    if status in _TERMINAL:
        raise InvalidStatusTransitionError(f"Leads in {status.value} status cannot be changed")


def allowed_status_targets(current: LeadStatus) -> list[LeadStatus]:
    return sorted(_ALLOWED.get(current, frozenset()), key=lambda item: item.value)


def assert_status_transition(current: LeadStatus, target: LeadStatus) -> None:
    if current == target:
        raise ValidationError("Lead is already in the requested status")
    allowed = _ALLOWED.get(current, frozenset())
    if target not in allowed:
        raise InvalidStatusTransitionError(
            f"Cannot change lead status from {current.value} to {target.value}"
        )

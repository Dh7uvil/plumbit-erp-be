"""Task status rules and available actions."""

from app.core.enums import TaskStatus


def assert_move_allowed(from_status: TaskStatus, to_status: TaskStatus) -> None:
    """All status transitions are allowed."""
    del from_status, to_status


def available_actions(
    status: TaskStatus,
    *,
    can_update: bool,
    can_delete: bool,
    can_move: bool,
    can_assign: bool,
) -> list[str]:
    del status
    actions: list[str] = []
    if can_update:
        actions.append("update")
    if can_delete:
        actions.append("delete")
    if can_assign:
        actions.append("assign")
    if can_move:
        actions.extend(f"move:{target.value}" for target in TaskStatus)
    return actions

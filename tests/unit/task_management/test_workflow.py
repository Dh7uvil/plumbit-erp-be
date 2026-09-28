"""Task workflow unit tests."""

from app.core.enums import TaskStatus
from app.task_management.tasks.workflow import assert_move_allowed, available_actions


def test_move_allowed_from_done_to_in_review() -> None:
    assert_move_allowed(TaskStatus.DONE, TaskStatus.IN_REVIEW)


def test_available_actions_include_all_move_targets() -> None:
    actions = available_actions(
        TaskStatus.TODO,
        can_update=True,
        can_delete=True,
        can_move=True,
        can_assign=True,
    )
    assert "update" in actions
    assert "delete" in actions
    assert "assign" in actions
    assert "move:TODO" in actions
    assert "move:IN_PROGRESS" in actions
    assert "move:DONE" in actions


def test_done_status_includes_all_moves() -> None:
    actions = available_actions(
        TaskStatus.DONE,
        can_update=True,
        can_delete=True,
        can_move=True,
        can_assign=True,
    )
    assert "move:IN_REVIEW" in actions
    assert "update" in actions

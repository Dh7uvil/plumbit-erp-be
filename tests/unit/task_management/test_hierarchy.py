"""Task hierarchy unit tests."""

from uuid import uuid4

import pytest

from app.core.enums import TaskType
from app.core.exceptions import ValidationError
from app.task_management.tasks.service import MAX_TASK_DEPTH, TaskService


def test_max_task_depth_constant() -> None:
    assert MAX_TASK_DEPTH == 3

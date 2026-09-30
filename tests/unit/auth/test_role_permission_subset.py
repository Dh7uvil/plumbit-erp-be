"""Unit tests for role permission grant subset checks."""

from __future__ import annotations

import pytest

from app.auth.service import validate_permission_grant_subset
from app.core.exceptions import ValidationError


def test_superadmin_can_grant_any_permission() -> None:
    validate_permission_grant_subset(
        {"identity.user.create", "identity.role.update"},
        frozenset({"identity.user.read"}),
        actor_is_superadmin=True,
    )


def test_actor_can_grant_subset_of_own_permissions() -> None:
    validate_permission_grant_subset(
        {"identity.user.read"},
        frozenset({"identity.user.read", "identity.user.update"}),
        actor_is_superadmin=False,
    )


def test_actor_cannot_grant_permissions_they_do_not_hold() -> None:
    with pytest.raises(ValidationError, match="Cannot grant permissions you do not hold"):
        validate_permission_grant_subset(
            {"identity.user.create"},
            frozenset({"identity.user.read"}),
            actor_is_superadmin=False,
        )

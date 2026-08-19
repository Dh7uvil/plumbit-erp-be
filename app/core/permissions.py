"""Strict helpers for ``module.resource.action`` permissions."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

_SEGMENT_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]*$", re.ASCII)


class InvalidPermissionError(ValueError):
    """Raised when a permission is not in canonical three-segment form."""


def _validate_segment(value: str, name: str) -> str:
    if not _SEGMENT_PATTERN.fullmatch(value):
        raise InvalidPermissionError(
            f"Permission {name} must be lowercase snake_case and start with a letter"
        )
    return value


@dataclass(frozen=True, slots=True)
class Permission:
    module: str
    resource: str
    action: str

    def __post_init__(self) -> None:
        _validate_segment(self.module, "module")
        _validate_segment(self.resource, "resource")
        _validate_segment(self.action, "action")

    def __str__(self) -> str:
        return f"{self.module}.{self.resource}.{self.action}"

    @classmethod
    def parse(cls, value: str) -> Permission:
        if value != value.strip():
            raise InvalidPermissionError("Permission must not contain surrounding whitespace")
        parts = value.split(".")
        if len(parts) != 3:
            raise InvalidPermissionError("Permission must contain exactly module.resource.action")
        return cls(module=parts[0], resource=parts[1], action=parts[2])


def build_permission(module: str, resource: str, action: str) -> str:
    """Build and validate a canonical permission string."""

    return str(Permission(module=module, resource=resource, action=action))


def parse_permission(value: str) -> Permission:
    return Permission.parse(value)


def has_permission(
    granted_permissions: Iterable[str | Permission],
    required_permission: str | Permission,
) -> bool:
    """Return whether a strictly parsed permission set contains the requirement."""

    required = (
        required_permission
        if isinstance(required_permission, Permission)
        else Permission.parse(required_permission)
    )
    granted = {
        (
            granted_value
            if isinstance(granted_value, Permission)
            else Permission.parse(granted_value)
        )
        for granted_value in granted_permissions
    }
    return required in granted

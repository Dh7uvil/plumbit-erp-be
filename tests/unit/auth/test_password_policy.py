"""Unit tests for password strength validation."""

from __future__ import annotations

import pytest

from app.auth.schemas import validate_password_strength


def test_validate_password_strength_accepts_valid_password() -> None:
    assert validate_password_strength("ValidPass1") == "ValidPass1"


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("short1A", "at least 8 characters"),
        ("alllowercase1", "uppercase letter"),
        ("ALLUPPERCASE1", "lowercase letter"),
        ("NoDigitsHere", "digit"),
    ],
)
def test_validate_password_strength_rejects_weak_passwords(
    password: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_password_strength(password)

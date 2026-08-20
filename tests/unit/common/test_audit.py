"""Unit tests for audit value sanitization."""

from uuid import uuid4

from app.common.services.audit import jsonable_value, sanitize_audit_values


def test_sanitize_audit_values_strips_credentials() -> None:
    user_id = uuid4()
    sanitized = sanitize_audit_values(
        {
            "id": user_id,
            "email": "a@example.com",
            "password": "secret",
            "password_hash": "hash",
            "access_token": "token",
        }
    )
    assert sanitized is not None
    assert sanitized["id"] == str(user_id)
    assert sanitized["email"] == "a@example.com"
    assert "password" not in sanitized
    assert "password_hash" not in sanitized
    assert "access_token" not in sanitized


def test_jsonable_value_handles_nested_containers() -> None:
    assert jsonable_value(("a", 1)) == ["a", 1]
    assert jsonable_value({"ok": True}) == {"ok": True}

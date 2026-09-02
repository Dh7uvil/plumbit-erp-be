"""Unit tests for audit value sanitization."""

from uuid import uuid4

from app.common.services.audit import audit_field_changes, jsonable_value, sanitize_audit_values


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


def test_audit_field_changes_empty_payloads() -> None:
    assert audit_field_changes(None, None) == []
    assert audit_field_changes({}, {}) == []
    assert audit_field_changes(None, {}) == []
    assert audit_field_changes({}, None) == []


def test_audit_field_changes_create_is_one_sided() -> None:
    assert audit_field_changes(None, {"name": "Acme", "code": "C-1"}) == [
        {"field": "code", "old_value": None, "new_value": "C-1"},
        {"field": "name", "old_value": None, "new_value": "Acme"},
    ]


def test_audit_field_changes_delete_is_one_sided() -> None:
    assert audit_field_changes({"name": "Acme"}, None) == [
        {"field": "name", "old_value": "Acme", "new_value": None},
    ]


def test_audit_field_changes_drops_unchanged_keys() -> None:
    old = {"name": "Acme", "code": "C-1", "notes": None}
    new = {"name": "Acme Ltd", "code": "C-1", "notes": None}
    assert audit_field_changes(old, new) == [
        {"field": "name", "old_value": "Acme", "new_value": "Acme Ltd"},
    ]


def test_audit_field_changes_nested_dict_inequality() -> None:
    old = {"settings": {"timezone": "UTC", "flag": True}}
    new = {"settings": {"timezone": "Asia/Dubai", "flag": True}}
    assert audit_field_changes(old, new) == [
        {
            "field": "settings",
            "old_value": {"timezone": "UTC", "flag": True},
            "new_value": {"timezone": "Asia/Dubai", "flag": True},
        },
    ]

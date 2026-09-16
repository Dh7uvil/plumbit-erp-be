"""Unit tests for environment-backed settings helpers."""

from app.core.config import DEFAULT_ALLOWED_UPLOAD_MIME_TYPES, parse_allowed_upload_mime_types


def test_blank_upload_mime_allowlist_keeps_defaults() -> None:
    assert parse_allowed_upload_mime_types("") == list(DEFAULT_ALLOWED_UPLOAD_MIME_TYPES)
    assert parse_allowed_upload_mime_types("   ") == list(DEFAULT_ALLOWED_UPLOAD_MIME_TYPES)
    assert "image/jpeg" in DEFAULT_ALLOWED_UPLOAD_MIME_TYPES


def test_upload_mime_allowlist_parses_comma_separated_values() -> None:
    assert parse_allowed_upload_mime_types("image/jpeg, image/png") == ["image/jpeg", "image/png"]

"""Unit tests for idempotency helper functions."""

import pytest

from app.common.idempotency.service import (
    hash_import_request,
    hash_request,
    optional_idempotency_key,
    require_idempotency_key,
)
from app.core.exceptions import ValidationError


def test_require_idempotency_key_rejects_missing() -> None:
    with pytest.raises(ValidationError, match="required"):
        require_idempotency_key(None)


def test_optional_idempotency_key_accepts_blank() -> None:
    assert optional_idempotency_key(None) is None
    assert optional_idempotency_key("   ") is None


def test_optional_idempotency_key_returns_trimmed_value() -> None:
    assert optional_idempotency_key("  abc  ") == "abc"


def test_hash_import_request_is_stable_for_same_payload() -> None:
    fields = {"mapping": "[]", "bank_account_id": "123"}
    content = b"csv,data"
    first = hash_import_request(
        method="POST", path="/api/v1/quotations/import", content=content, fields=fields
    )
    second = hash_import_request(
        method="POST", path="/api/v1/quotations/import", content=content, fields=fields
    )
    assert first == second
    assert first != hash_request(method="POST", path="/api/v1/quotations/import", body=content)

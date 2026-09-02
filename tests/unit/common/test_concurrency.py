"""Unit tests for If-Match / document version parsing."""

import pytest

from app.common.utils.concurrency import parse_if_match, require_document_version
from app.core.exceptions import ValidationError


def test_parse_if_match_accepts_integer_and_etag() -> None:
    assert parse_if_match("3") == 3
    assert parse_if_match('"4"') == 4
    assert parse_if_match('W/"5"') == 5
    assert parse_if_match(None) is None


def test_require_document_version_prefers_matching_sources() -> None:
    assert require_document_version(if_match="2") == 2
    assert require_document_version(if_match=None, body_version=7) == 7
    with pytest.raises(ValidationError):
        require_document_version(if_match=None, body_version=None)
    with pytest.raises(ValidationError):
        require_document_version(if_match="1", body_version=2)

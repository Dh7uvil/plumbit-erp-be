"""Unit tests for upload filename, size, and MIME validation."""

import io
import zipfile

import pytest

from app.common.utils.files import (
    MIME_CSV,
    MIME_JSON,
    MIME_PDF,
    MIME_PNG,
    MIME_XLSX,
    detect_content_type,
    sanitize_filename,
    validate_upload,
)
from app.core.exceptions import ValidationError

_ALLOWED = (MIME_PDF, MIME_PNG, MIME_JSON, MIME_CSV, MIME_XLSX)
_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _xlsx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    return buffer.getvalue()


def test_sanitize_filename_strips_paths_and_unsafe_characters() -> None:
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("C:\\Windows\\quote.pdf") == "quote.pdf"
    assert sanitize_filename("my quote (1).pdf") == "my_quote_1_.pdf"
    assert sanitize_filename("") == "upload"
    assert sanitize_filename("...") == "upload"


def test_detect_content_type_from_magic_bytes() -> None:
    assert detect_content_type(_PDF) == MIME_PDF
    assert detect_content_type(_PNG) == MIME_PNG
    assert detect_content_type(b'{"ok": true}') == MIME_JSON
    assert detect_content_type(b"a,b,c\n1,2,3\n") == MIME_CSV
    assert detect_content_type(_xlsx_bytes()) == MIME_XLSX
    assert detect_content_type(b"\x00\x01\x02not-a-file") is None


def test_validate_upload_accepts_allowed_pdf() -> None:
    result = validate_upload(
        _PDF,
        filename="../../invoice.pdf",
        max_upload_size_mb=1,
        allowed_mime_types=_ALLOWED,
    )
    assert result.filename == "invoice.pdf"
    assert result.content_type == MIME_PDF
    assert result.size_bytes == len(_PDF)


def test_validate_upload_rejects_empty_file() -> None:
    with pytest.raises(ValidationError, match="empty"):
        validate_upload(
            b"",
            filename="empty.pdf",
            max_upload_size_mb=1,
            allowed_mime_types=_ALLOWED,
        )


def test_validate_upload_rejects_oversized_file() -> None:
    oversized = b"%PDF-" + b"x" * (1024 * 1024 + 1)
    with pytest.raises(ValidationError, match="maximum size"):
        validate_upload(
            oversized,
            filename="huge.pdf",
            max_upload_size_mb=1,
            allowed_mime_types=_ALLOWED,
        )


def test_validate_upload_rejects_disallowed_or_unknown_type() -> None:
    with pytest.raises(ValidationError, match="not allowed"):
        validate_upload(
            _PNG,
            filename="photo.png",
            max_upload_size_mb=1,
            allowed_mime_types=(MIME_PDF,),
        )
    with pytest.raises(ValidationError, match="could not be determined"):
        validate_upload(
            b"\x00\x01\x02",
            filename="blob.bin",
            max_upload_size_mb=1,
            allowed_mime_types=_ALLOWED,
        )

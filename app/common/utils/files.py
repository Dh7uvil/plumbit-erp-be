"""Upload filename, size, and content-type validation.

Never trust the client-supplied filename, extension, or Content-Type header.
MIME type is detected from the file bytes.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass

from app.core.exceptions import ValidationError

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILENAME_STEM = 100
_MAX_FILENAME_EXT = 20

_PDF_MAGIC = b"%PDF-"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_GIF87_MAGIC = b"GIF87a"
_GIF89_MAGIC = b"GIF89a"
_WEBP_RIFF = b"RIFF"
_WEBP_TAG = b"WEBP"
_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_OLE_WORD = b"W\x00o\x00r\x00d\x00D\x00o\x00c\x00u\x00m\x00e\x00n\x00t"
_OLE_EXCEL_WORKBOOK = b"W\x00o\x00r\x00k\x00b\x00o\x00o\x00k"
_OLE_EXCEL_BOOK = b"B\x00o\x00o\x00k\x00"
_OLE_POWERPOINT = b"P\x00o\x00w\x00e\x00r\x00P\x00o\x00i\x00n\x00t"

MIME_PDF = "application/pdf"
MIME_JPEG = "image/jpeg"
MIME_PNG = "image/png"
MIME_GIF = "image/gif"
MIME_WEBP = "image/webp"
MIME_JSON = "application/json"
MIME_CSV = "text/csv"
MIME_DOC = "application/msword"
MIME_XLS = "application/vnd.ms-excel"
MIME_PPT = "application/vnd.ms-powerpoint"
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    """Sanitized filename, detected MIME type, and raw bytes."""

    filename: str
    content_type: str
    content: bytes
    size_bytes: int


def max_upload_bytes(max_upload_size_mb: int) -> int:
    """Convert the configured megabyte cap into a byte limit."""

    return max_upload_size_mb * 1024 * 1024


def sanitize_filename(filename: str | None) -> str:
    """Return a path-safe basename, never trusting directories or empty names."""

    raw = (filename or "").replace("\\", "/")
    name = raw.rsplit("/", 1)[-1].strip()
    name = name.lstrip(".")
    name = _UNSAFE_FILENAME.sub("_", name).strip("._")
    if not name:
        return "upload"
    if len(name) <= _MAX_FILENAME_STEM + 1 + _MAX_FILENAME_EXT:
        return name[: _MAX_FILENAME_STEM + 1 + _MAX_FILENAME_EXT]
    if "." in name:
        stem, ext = name.rsplit(".", 1)
        return f"{stem[:_MAX_FILENAME_STEM]}.{ext[:_MAX_FILENAME_EXT]}"
    return name[:_MAX_FILENAME_STEM]


def ensure_within_size_limit(size_bytes: int, *, max_upload_size_mb: int) -> None:
    """Reject empty files and payloads over the configured cap."""

    if size_bytes <= 0:
        raise ValidationError("File is empty")
    limit = max_upload_bytes(max_upload_size_mb)
    if size_bytes > limit:
        raise ValidationError(
            f"File exceeds the maximum size of {max_upload_size_mb} MB",
            details={"max_upload_size_mb": max_upload_size_mb, "size_bytes": size_bytes},
        )


def detect_content_type(data: bytes) -> str | None:
    """Detect MIME type from magic bytes and lightweight content sniffing."""

    if not data:
        return None
    if data.startswith(_PDF_MAGIC):
        return MIME_PDF
    if data.startswith(_PNG_MAGIC):
        return MIME_PNG
    if data.startswith(_JPEG_MAGIC):
        return MIME_JPEG
    if data.startswith(_GIF87_MAGIC) or data.startswith(_GIF89_MAGIC):
        return MIME_GIF
    if data.startswith(_WEBP_RIFF) and data[8:12] == _WEBP_TAG:
        return MIME_WEBP
    if data.startswith(_OLE_MAGIC):
        return _detect_ole(data)
    if data.startswith(_ZIP_MAGIC):
        return _detect_ooxml(data)
    if _looks_like_json(data):
        return MIME_JSON
    if _looks_like_csv(data):
        return MIME_CSV
    return None


def ensure_allowed_content_type(content_type: str, *, allowed: Sequence[str]) -> str:
    """Reject a detected type that is not on the configured allowlist."""

    if content_type not in allowed:
        raise ValidationError(
            "File type is not allowed",
            details={"content_type": content_type},
        )
    return content_type


def validate_upload(
    content: bytes,
    *,
    filename: str | None,
    max_upload_size_mb: int,
    allowed_mime_types: Sequence[str],
) -> ValidatedUpload:
    """Sanitize, size-check, and MIME-detect an uploaded payload."""

    ensure_within_size_limit(len(content), max_upload_size_mb=max_upload_size_mb)
    detected = detect_content_type(content)
    if detected is None:
        raise ValidationError("File type could not be determined")
    ensure_allowed_content_type(detected, allowed=allowed_mime_types)
    safe_name = sanitize_filename(filename)
    return ValidatedUpload(
        filename=safe_name,
        content_type=detected,
        content=content,
        size_bytes=len(content),
    )


def _detect_ole(data: bytes) -> str | None:
    if _OLE_WORD in data:
        return MIME_DOC
    if _OLE_EXCEL_WORKBOOK in data or _OLE_EXCEL_BOOK in data:
        return MIME_XLS
    if _OLE_POWERPOINT in data:
        return MIME_PPT
    return None


def _detect_ooxml(data: bytes) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile:
        return None
    if any(name.startswith("word/") for name in names):
        return MIME_DOCX
    if any(name.startswith("xl/") for name in names):
        return MIME_XLSX
    if any(name.startswith("ppt/") for name in names):
        return MIME_PPTX
    return None


def _looks_like_json(data: bytes) -> bool:
    stripped = data.lstrip()
    if not stripped or stripped[:1] not in (b"{", b"["):
        return False
    try:
        json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return True


def _looks_like_csv(data: bytes) -> bool:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    if not text.strip() or _looks_like_json(data):
        return False
    sample = text.splitlines()[:20]
    return any("," in line or ";" in line or "\t" in line for line in sample)

"""Optimistic concurrency helpers for workflow documents."""

from app.core.exceptions import ValidationError


def parse_if_match(value: str | None) -> int | None:
    """Parse an If-Match header as a document version integer."""

    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.startswith("W/"):
        raw = raw[2:].strip()
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        raw = raw[1:-1]
    try:
        version = int(raw)
    except ValueError as exc:
        raise ValidationError("If-Match must be a document version integer") from exc
    if version < 1:
        raise ValidationError("If-Match must be a document version integer")
    return version


def require_document_version(*, if_match: str | None, body_version: int | None = None) -> int:
    """Return the expected version from If-Match or a body field."""

    header_version = parse_if_match(if_match)
    if header_version is not None and body_version is not None and header_version != body_version:
        raise ValidationError("If-Match and body version do not match")
    version = header_version if header_version is not None else body_version
    if version is None:
        raise ValidationError("If-Match or version is required")
    return version

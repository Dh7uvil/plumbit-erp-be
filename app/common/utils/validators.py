"""Small, domain-neutral validation helpers."""

import re
from uuid import UUID

_CURRENCY_CODE_PATTERN = re.compile(r"^[A-Z]{3}$")


def normalize_required_text(value: str, *, field_name: str = "value") -> str:
    """Trim required text and reject an empty result."""

    normalized = value.strip()
    if not normalized:
        msg = f"{field_name} must not be empty"
        raise ValueError(msg)
    return normalized


def normalize_currency_code(value: str) -> str:
    """Normalize and validate an ISO-style three-letter currency code."""

    normalized = value.strip().upper()
    if _CURRENCY_CODE_PATTERN.fullmatch(normalized) is None:
        msg = "currency code must contain exactly three ASCII letters"
        raise ValueError(msg)
    return normalized


def parse_uuid(value: str | UUID, *, field_name: str = "value") -> UUID:
    """Parse a UUID while returning a field-specific validation error."""

    if isinstance(value, UUID):
        return value
    try:
        return UUID(value)
    except ValueError as exc:
        msg = f"{field_name} must be a valid UUID"
        raise ValueError(msg) from exc

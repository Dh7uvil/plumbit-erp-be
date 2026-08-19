"""UTC date and time helpers."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return the current timezone-aware UTC datetime."""

    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Attach UTC to naive values or convert aware values to UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)

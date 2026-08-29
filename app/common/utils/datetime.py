"""UTC date and time helpers."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    """Return the current timezone-aware UTC datetime."""

    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Attach UTC to naive values or convert aware values to UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def today_in_timezone(timezone_name: str) -> date:
    """Return today's calendar date in the given IANA timezone."""

    try:
        zone = ZoneInfo(timezone_name)
    except (KeyError, ValueError):
        zone = ZoneInfo("UTC")
    return datetime.now(zone).date()

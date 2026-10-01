"""Feature flag guard for communication module."""

from app.core.config import get_settings
from app.core.exceptions import ResourceNotFoundError


def require_communication_enabled() -> None:
    if not get_settings().feature_communication_enabled:
        raise ResourceNotFoundError("Communication is not enabled")

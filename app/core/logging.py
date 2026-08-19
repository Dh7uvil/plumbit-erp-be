"""JSON stdlib logging with recursive secret redaction."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import UTC, date, datetime
from enum import Enum
from typing import Final, cast
from uuid import UUID

from app.core.middleware import get_request_id, get_tenant_id, get_user_id

REDACTED: Final = "[REDACTED]"
_SENSITIVE_KEY_PARTS: Final = (
    "password",
    "passwd",
    "pwd",
    "token",
    "secret",
    "authorization",
    "cookie",
    "credential",
    "api_key",
    "private_key",
    "card_number",
    "cvv",
)
_STANDARD_LOG_RECORD_FIELDS: Final = frozenset(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
}


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_").replace(" ", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _redact(value: object, seen: set[int]) -> object:
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in seen:
            return "<recursive>"
        seen.add(identity)
        try:
            return {
                str(key): REDACTED if _is_sensitive_key(key) else _redact(item, seen)
                for key, item in value.items()
            }
        finally:
            seen.remove(identity)

    if isinstance(value, (list, tuple, set, frozenset)):
        identity = id(value)
        if identity in seen:
            return "<recursive>"
        seen.add(identity)
        try:
            return [_redact(item, seen) for item in value]
        finally:
            seen.remove(identity)

    return value


def redact_secrets(value: object) -> object:
    """Return a recursively redacted, logging-safe copy of structured data."""

    return _redact(value, set())


class SecretRedactionFilter(logging.Filter):
    """Redact nested secrets from messages, interpolation args, and extras."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, (Mapping, list, tuple, set, frozenset)):
            record.msg = redact_secrets(record.msg)

        if isinstance(record.args, Mapping):
            record.args = cast(Mapping[str, object], redact_secrets(record.args))
        elif isinstance(record.args, tuple):
            redacted_args = redact_secrets(record.args)
            if isinstance(redacted_args, list):
                record.args = tuple(redacted_args)

        for key, value in tuple(record.__dict__.items()):
            if key not in _STANDARD_LOG_RECORD_FIELDS:
                record.__dict__[key] = REDACTED if _is_sensitive_key(key) else redact_secrets(value)
        return True


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (UUID, Enum)):
        return str(value)
    return f"<{type(value).__name__}>"


class JsonFormatter(logging.Formatter):
    """Serialize each log record as one compact JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or get_request_id(),
            "tenant_id": getattr(record, "tenant_id", None) or get_tenant_id(),
            "user_id": getattr(record, "user_id", None) or get_user_id(),
        }

        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_FIELDS and key not in payload:
                payload[key] = value

        if record.exc_info is not None and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__

        return json.dumps(
            redact_secrets(payload),
            default=_json_default,
            ensure_ascii=False,
            separators=(",", ":"),
        )


def configure_logging(level: str | int = logging.INFO) -> None:
    """Configure the process root logger once for JSON output."""

    handler = logging.StreamHandler()
    handler.addFilter(SecretRedactionFilter())
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

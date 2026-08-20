"""Append-only audit trail writer used by feature-slice services."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.models.audit_log import AuditLog
from app.core.enums import AuditAction, AuditStatus
from app.core.middleware import get_client_ip, get_user_agent

_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "current_password",
        "new_password",
        "refresh_token",
        "access_token",
        "token",
        "secret",
    }
)


def jsonable_value(value: object) -> object:
    """Convert common Python values into JSON-serializable forms."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return str(value)
    if isinstance(value, dict):
        return {str(key): jsonable_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable_value(item) for item in value]
    return str(value)


def sanitize_audit_values(values: dict[str, object] | None) -> dict[str, object] | None:
    """Drop credentials and coerce remaining values for JSONB storage."""

    if not values:
        return None
    sanitized = {
        key: jsonable_value(value) for key, value in values.items() if key not in _SENSITIVE_KEYS
    }
    return sanitized or None


class AuditWriter:
    """Persist one audit row; callers own the surrounding transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def write(
        self,
        *,
        tenant_id: UUID,
        action: AuditAction | str,
        module: str,
        entity_type: str,
        entity_id: UUID | None = None,
        user_id: UUID | None = None,
        old_values: dict[str, object] | None = None,
        new_values: dict[str, object] | None = None,
        status: AuditStatus | str = AuditStatus.SUCCESS,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        """Stage an audit row and flush. Never logs passwords or tokens."""

        row = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=str(action),
            module=module,
            entity_type=entity_type,
            entity_id=entity_id,
            old_values=sanitize_audit_values(old_values),
            new_values=sanitize_audit_values(new_values),
            ip_address=_truncate_ip(ip_address if ip_address is not None else get_client_ip()),
            user_agent=_truncate_user_agent(
                user_agent if user_agent is not None else get_user_agent()
            ),
            status=str(status),
        )
        self.session.add(row)
        await self.session.flush()
        return row


def _truncate_ip(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:45]


def _truncate_user_agent(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:2000]

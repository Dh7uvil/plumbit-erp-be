"""Cross-cutting ORM models shared by more than one module."""

from app.common.models.audit_log import AuditLog

__all__ = ["AuditLog"]

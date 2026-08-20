"""Shared services used by more than one module."""

from app.common.services.audit import AuditWriter

__all__ = ["AuditWriter"]

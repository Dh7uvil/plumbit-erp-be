"""Async report export jobs."""


from sqlalchemy import Index, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantModel
from app.db.mixins import AuditUserMixin


class ReportExportJob(AuditUserMixin, TenantModel):
    """Background export of a financial report to CSV, Excel, or PDF."""

    __tablename__ = "report_export_jobs"
    __table_args__ = (Index("ix_report_export_jobs_tenant_status", "tenant_id", "status"),)

    report_key: Mapped[str] = mapped_column(String(60), nullable=False)
    export_format: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    params: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    filename: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

"""Quality inspection document models."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import QUANTITY_PRECISION, QUANTITY_SCALE
from app.db.base import SoftDeleteTenantModel, TenantModel
from app.db.mixins import AuditUserMixin

_QTY = Numeric(QUANTITY_PRECISION, QUANTITY_SCALE)


class QualityInspection(AuditUserMixin, SoftDeleteTenantModel):
    """Inspection of a goods receipt. Approve releases hold or writes off rejected qty."""

    __tablename__ = "quality_inspections"
    __table_args__ = (
        Index(
            "uq_quality_inspections_tenant_id_document_number_active",
            "tenant_id",
            "document_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_quality_inspections_tenant_id_status", "tenant_id", "status"),
        Index("ix_quality_inspections_goods_receipt_id", "goods_receipt_id"),
    )

    document_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'DRAFT'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    goods_receipt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("goods_receipts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    inspection_date: Mapped[date] = mapped_column(Date, nullable=False)
    inspector_user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    lines: Mapped[list["QualityInspectionLine"]] = relationship(
        back_populates="inspection",
        cascade="all, delete-orphan",
        order_by="QualityInspectionLine.line_number",
    )


class QualityInspectionLine(TenantModel):
    """Inspected / accepted / rejected / rework quantities for one GRN line."""

    __tablename__ = "quality_inspection_lines"
    __table_args__ = (
        UniqueConstraint(
            "quality_inspection_id",
            "line_number",
            name="uq_quality_inspection_lines_header_line_number",
        ),
        UniqueConstraint(
            "quality_inspection_id",
            "goods_receipt_line_id",
            name="uq_quality_inspection_lines_header_grn_line",
        ),
        Index("ix_quality_inspection_lines_quality_inspection_id", "quality_inspection_id"),
    )

    quality_inspection_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("quality_inspections.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    goods_receipt_line_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("goods_receipt_lines.id", ondelete="RESTRICT"),
        nullable=False,
    )
    qty_inspected: Mapped[Decimal] = mapped_column(_QTY, nullable=False)
    qty_accepted: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))
    qty_rejected: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))
    qty_rework: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))
    disposition: Mapped[str | None] = mapped_column(String(30), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    inspection: Mapped[QualityInspection] = relationship(back_populates="lines")

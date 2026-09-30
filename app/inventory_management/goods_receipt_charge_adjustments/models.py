"""GRN charge adjustment document models."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
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

from app.core.constants import MONEY_PRECISION, MONEY_SCALE
from app.db.base import SoftDeleteTenantModel, TenantModel
from app.db.mixins import AuditUserMixin

_MONEY = Numeric(MONEY_PRECISION, MONEY_SCALE)


class GoodsReceiptChargeAdjustment(AuditUserMixin, SoftDeleteTenantModel):
    """Draft-or-posted adjustment to inventoriable GRN charges after posting."""

    __tablename__ = "goods_receipt_charge_adjustments"
    __table_args__ = (
        Index(
            "uq_grn_charge_adjustments_tenant_id_document_number_active",
            "tenant_id",
            "document_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_grn_charge_adjustments_tenant_id_status", "tenant_id", "status"),
        Index("ix_grn_charge_adjustments_tenant_id_document_date", "tenant_id", "document_date"),
        Index("ix_grn_charge_adjustments_goods_receipt_id", "goods_receipt_id"),
    )

    document_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'DRAFT'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    document_date: Mapped[date] = mapped_column(Date, nullable=False)
    goods_receipt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("goods_receipts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    branch_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_by: Mapped[UUID | None] = mapped_column(
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

    lines: Mapped[list["GoodsReceiptChargeAdjustmentLine"]] = relationship(
        back_populates="adjustment",
        cascade="all, delete-orphan",
        order_by="GoodsReceiptChargeAdjustmentLine.line_number",
    )


class GoodsReceiptChargeAdjustmentLine(TenantModel):
    """Signed delta against a posted GRN charge row."""

    __tablename__ = "goods_receipt_charge_adjustment_lines"
    __table_args__ = (
        UniqueConstraint(
            "goods_receipt_charge_adjustment_id",
            "line_number",
            name="uq_grn_charge_adjustment_lines_header_line_number",
        ),
        Index(
            "ix_grn_charge_adjustment_lines_adjustment_id",
            "goods_receipt_charge_adjustment_id",
        ),
        Index(
            "ix_grn_charge_adjustment_lines_goods_receipt_charge_id",
            "goods_receipt_charge_id",
        ),
    )

    goods_receipt_charge_adjustment_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("goods_receipt_charge_adjustments.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    goods_receipt_charge_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("goods_receipt_charges.id", ondelete="RESTRICT"),
        nullable=False,
    )
    adjustment_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    base_adjustment_amount: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    adjustment: Mapped[GoodsReceiptChargeAdjustment] = relationship(back_populates="lines")

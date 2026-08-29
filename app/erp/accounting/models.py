"""Accounting master ORM models."""

from decimal import Decimal

from sqlalchemy import Boolean, Index, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MONEY_PRECISION, MONEY_SCALE
from app.db.base import SoftDeleteTenantModel
from app.db.mixins import AuditUserMixin, IsActiveMixin


class Tax(AuditUserMixin, IsActiveMixin, SoftDeleteTenantModel):
    """UAE VAT tax master."""

    __tablename__ = "taxes"
    __table_args__ = (
        Index(
            "uq_taxes_tenant_id_name_active",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_taxes_tenant_id_default_active",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_default IS TRUE AND deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    tax_category: Mapped[str] = mapped_column(String(30), nullable=False)
    rate: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=False,
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )


class PaymentTerm(AuditUserMixin, IsActiveMixin, SoftDeleteTenantModel):
    """Named payment term copied onto commercial documents."""

    __tablename__ = "payment_terms"
    __table_args__ = (
        Index(
            "uq_payment_terms_tenant_id_name_active",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class TermsTemplate(AuditUserMixin, IsActiveMixin, SoftDeleteTenantModel):
    """Reusable terms-and-conditions body for quotes."""

    __tablename__ = "terms_templates"
    __table_args__ = (
        Index(
            "uq_terms_templates_tenant_id_name_active",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_terms_templates_tenant_id_default_active",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_default IS TRUE AND deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )


class DocumentSequence(AuditUserMixin, IsActiveMixin, SoftDeleteTenantModel):
    """Locked counter used to allocate human-readable document numbers."""

    __tablename__ = "document_sequences"
    __table_args__ = (
        Index(
            "uq_document_sequences_tenant_type_series_year_active",
            "tenant_id",
            "document_type",
            "series",
            "fiscal_year",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    document_type: Mapped[str] = mapped_column(String(30), nullable=False)
    series: Mapped[str] = mapped_column(String(20), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    next_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    padding: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=6,
        server_default=text("6"),
    )

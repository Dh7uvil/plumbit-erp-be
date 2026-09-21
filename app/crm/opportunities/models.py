"""Opportunity ORM models."""

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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MONEY_PRECISION, MONEY_SCALE
from app.db.base import SoftDeleteTenantModel, TenantModel
from app.db.mixins import AuditUserMixin


class OpportunityNumberCounter(TenantModel):
    """Per-tenant counter for OPP-##### allocation."""

    __tablename__ = "crm_opportunity_number_counters"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_crm_opportunity_number_counters_tenant_id"),
    )

    next_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )


class Opportunity(AuditUserMixin, SoftDeleteTenantModel):
    """CRM sales opportunity in a pipeline stage."""

    __tablename__ = "crm_opportunities"
    __table_args__ = (
        Index(
            "uq_crm_opportunities_tenant_id_opportunity_number_active",
            "tenant_id",
            "opportunity_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_crm_opportunities_tenant_id_status", "tenant_id", "status"),
        Index("ix_crm_opportunities_tenant_id_pipeline_id", "tenant_id", "pipeline_id"),
        Index("ix_crm_opportunities_tenant_id_stage_id", "tenant_id", "stage_id"),
        Index("ix_crm_opportunities_tenant_id_owner_id", "tenant_id", "owner_id"),
        Index("ix_crm_opportunities_tenant_id_customer_id", "tenant_id", "customer_id"),
    )

    opportunity_number: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
    )
    contact_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    pipeline_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("crm_pipelines.id", ondelete="RESTRICT"),
        nullable=False,
    )
    stage_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("crm_pipeline_stages.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=True,
    )
    currency_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=True,
    )
    probability: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=True,
    )
    expected_close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'OPEN'"))
    lost_reason_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("crm_lost_reasons.id", ondelete="SET NULL"),
        nullable=True,
    )
    owner_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("crm_lead_sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    lead_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("crm_leads.id", ondelete="SET NULL"),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class OpportunityStageHistory(TenantModel):
    """Append-only stage transition log for an opportunity."""

    __tablename__ = "crm_opportunity_stage_history"
    __table_args__ = (
        Index("ix_crm_opportunity_stage_history_opportunity_id", "opportunity_id"),
    )

    opportunity_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("crm_opportunities.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_stage_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("crm_pipeline_stages.id", ondelete="SET NULL"),
        nullable=True,
    )
    to_stage_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("crm_pipeline_stages.id", ondelete="RESTRICT"),
        nullable=False,
    )
    changed_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

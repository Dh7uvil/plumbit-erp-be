"""Campaign ORM models."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MONEY_PRECISION, MONEY_SCALE
from app.db.base import SoftDeleteTenantModel, TenantModel
from app.db.mixins import AuditUserMixin


class Campaign(AuditUserMixin, SoftDeleteTenantModel):
    """Marketing campaign used to attribute leads and opportunities."""

    __tablename__ = "crm_campaigns"
    __table_args__ = (
        Index(
            "uq_crm_campaigns_tenant_id_name_active",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_crm_campaigns_tenant_id_status", "tenant_id", "status"),
        Index("ix_crm_campaigns_tenant_id_owner_id", "tenant_id", "owner_id"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    campaign_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'PLANNED'")
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    budgeted_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=True,
    )
    actual_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=True,
    )
    expected_revenue: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=True,
    )
    owner_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class CampaignMember(TenantModel):
    """Lead or contact enrolled in a campaign."""

    __tablename__ = "crm_campaign_members"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "campaign_id",
            "member_type",
            "member_id",
            name="uq_crm_campaign_members_tenant_campaign_member",
        ),
        Index("ix_crm_campaign_members_campaign_id", "campaign_id"),
        Index(
            "ix_crm_campaign_members_tenant_member",
            "tenant_id",
            "member_type",
            "member_id",
        ),
    )

    campaign_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("crm_campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    member_type: Mapped[str] = mapped_column(String(20), nullable=False)
    member_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    member_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'PLANNED'")
    )

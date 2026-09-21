"""Sales pipeline and stage ORM models."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MONEY_PRECISION, MONEY_SCALE
from app.db.base import SoftDeleteTenantModel, TenantModel
from app.db.mixins import AuditUserMixin, IsActiveMixin


class Pipeline(AuditUserMixin, IsActiveMixin, SoftDeleteTenantModel):
    """Tenant-owned opportunity pipeline."""

    __tablename__ = "crm_pipelines"
    __table_args__ = (
        Index(
            "uq_crm_pipelines_tenant_id_name_active",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_crm_pipelines_tenant_id_default_active",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_default IS TRUE AND deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )


class PipelineStage(TenantModel):
    """Ordered stage within a pipeline."""

    __tablename__ = "crm_pipeline_stages"
    __table_args__ = (
        Index(
            "uq_crm_pipeline_stages_tenant_pipeline_name",
            "tenant_id",
            "pipeline_id",
            "name",
            unique=True,
        ),
        Index("ix_crm_pipeline_stages_pipeline_id", "pipeline_id"),
    )

    pipeline_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("crm_pipelines.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    probability: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=False,
    )
    stage_kind: Mapped[str] = mapped_column(String(20), nullable=False)

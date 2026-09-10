"""Shipment logistics models. Moves no stock and writes no ledger entry."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import QUANTITY_PRECISION, QUANTITY_SCALE
from app.db.base import SoftDeleteTenantModel
from app.db.mixins import AuditUserMixin

_QTY = Numeric(QUANTITY_PRECISION, QUANTITY_SCALE)


class Shipment(AuditUserMixin, SoftDeleteTenantModel):
    """Export/domestic logistics wrapper grouping posted delivery notes."""

    __tablename__ = "shipments"
    __table_args__ = (
        Index(
            "uq_shipments_tenant_id_document_number_active",
            "tenant_id",
            "document_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_shipments_tenant_id_status", "tenant_id", "status"),
    )

    document_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'DRAFT'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    shipment_type: Mapped[str] = mapped_column(String(30), nullable=False)
    transport_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    incoterm: Mapped[str | None] = mapped_column(String(10), nullable=True)
    container_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    seal_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    carrier_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    vessel_or_flight_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    voyage_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    bl_awb_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    bl_awb_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    freight_forwarder_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
    )
    port_of_loading: Mapped[str | None] = mapped_column(String(120), nullable=True)
    port_of_discharge: Mapped[str | None] = mapped_column(String(120), nullable=True)
    etd: Mapped[date | None] = mapped_column(Date, nullable=True)
    eta: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_departure_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_arrival_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    gross_weight: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    net_weight: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    total_packages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

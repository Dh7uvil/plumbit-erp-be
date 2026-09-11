"""Shipment request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.schemas.filters import BaseFilter
from app.common.schemas.related_documents import RelatedDocumentRef
from app.core.enums import Incoterm, ShipmentStatus, ShipmentType, TransportMode


class ShipmentFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "document_number", "status", "etd", "eta"}
    )
    status: ShipmentStatus | None = None
    shipment_type: ShipmentType | None = None
    transport_mode: TransportMode | None = None


class ShipmentCreate(BaseModel):
    shipment_type: ShipmentType
    transport_mode: TransportMode
    incoterm: Incoterm | None = None
    container_number: str | None = Field(default=None, max_length=80)
    seal_number: str | None = Field(default=None, max_length=80)
    carrier_name: str | None = Field(default=None, max_length=120)
    vessel_or_flight_no: str | None = Field(default=None, max_length=80)
    voyage_number: str | None = Field(default=None, max_length=80)
    bl_awb_number: str | None = Field(default=None, max_length=80)
    bl_awb_date: date | None = None
    freight_forwarder_id: UUID | None = None
    port_of_loading: str | None = Field(default=None, max_length=120)
    port_of_discharge: str | None = Field(default=None, max_length=120)
    etd: date | None = None
    eta: date | None = None
    gross_weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    net_weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    total_packages: int | None = Field(default=None, ge=0)
    notes: str | None = None

    @field_validator(
        "container_number",
        "seal_number",
        "carrier_name",
        "vessel_or_flight_no",
        "voyage_number",
        "bl_awb_number",
        "port_of_loading",
        "port_of_discharge",
        "notes",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ShipmentUpdate(BaseModel):
    shipment_type: ShipmentType | None = None
    transport_mode: TransportMode | None = None
    incoterm: Incoterm | None = None
    container_number: str | None = Field(default=None, max_length=80)
    seal_number: str | None = Field(default=None, max_length=80)
    carrier_name: str | None = Field(default=None, max_length=120)
    vessel_or_flight_no: str | None = Field(default=None, max_length=80)
    voyage_number: str | None = Field(default=None, max_length=80)
    bl_awb_number: str | None = Field(default=None, max_length=80)
    bl_awb_date: date | None = None
    freight_forwarder_id: UUID | None = None
    port_of_loading: str | None = Field(default=None, max_length=120)
    port_of_discharge: str | None = Field(default=None, max_length=120)
    etd: date | None = None
    eta: date | None = None
    gross_weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    net_weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    total_packages: int | None = Field(default=None, ge=0)
    notes: str | None = None
    version: int | None = Field(default=None, ge=1)

    @field_validator(
        "container_number",
        "seal_number",
        "carrier_name",
        "vessel_or_flight_no",
        "voyage_number",
        "bl_awb_number",
        "port_of_loading",
        "port_of_discharge",
        "notes",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ShipmentTrackingUpdate(BaseModel):
    carrier_name: str | None = Field(default=None, max_length=120)
    vessel_or_flight_no: str | None = Field(default=None, max_length=80)
    voyage_number: str | None = Field(default=None, max_length=80)
    bl_awb_number: str | None = Field(default=None, max_length=80)
    bl_awb_date: date | None = None
    etd: date | None = None
    eta: date | None = None
    actual_departure_date: date | None = None
    actual_arrival_date: date | None = None
    version: int | None = Field(default=None, ge=1)

    @field_validator("carrier_name", "vessel_or_flight_no", "voyage_number", "bl_awb_number")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ShipmentAttachNotesRequest(BaseModel):
    delivery_note_ids: list[UUID] = Field(min_length=1)


class ShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    status: ShipmentStatus
    version: int
    shipment_type: ShipmentType
    transport_mode: TransportMode
    incoterm: Incoterm | None
    container_number: str | None
    seal_number: str | None
    carrier_name: str | None
    vessel_or_flight_no: str | None
    voyage_number: str | None
    bl_awb_number: str | None
    bl_awb_date: date | None
    freight_forwarder_id: UUID | None
    port_of_loading: str | None
    port_of_discharge: str | None
    etd: date | None
    eta: date | None
    actual_departure_date: date | None
    actual_arrival_date: date | None
    gross_weight: Decimal | None
    net_weight: Decimal | None
    total_packages: int | None
    notes: str | None
    available_actions: list[str] = Field(default_factory=list)
    related_documents: list[RelatedDocumentRef] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

"""Quality inspection request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import QcDisposition, QualityInspectionStatus


class QualityInspectionFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "document_number", "inspection_date", "status"}
    )
    status: QualityInspectionStatus | None = None
    goods_receipt_id: UUID | None = None
    inspection_date_from: date | None = None
    inspection_date_to: date | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> "QualityInspectionFilter":
        if (
            self.inspection_date_from is not None
            and self.inspection_date_to is not None
            and self.inspection_date_from > self.inspection_date_to
        ):
            raise ValueError("inspection_date_from must be before or equal to inspection_date_to")
        return self


class QualityInspectionLineInput(BaseModel):
    goods_receipt_line_id: UUID
    qty_inspected: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    qty_accepted: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=6)
    qty_rejected: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=6)
    qty_rework: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=6)
    disposition: QcDisposition | None = None
    notes: str | None = None

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class QualityInspectionLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    goods_receipt_line_id: UUID
    qty_inspected: Decimal
    qty_accepted: Decimal
    qty_rejected: Decimal
    qty_rework: Decimal
    disposition: QcDisposition | None
    notes: str | None


class QualityInspectionCreate(BaseModel):
    goods_receipt_id: UUID
    inspection_date: date | None = None
    inspector_user_id: UUID | None = None
    notes: str | None = None
    lines: list[QualityInspectionLineInput] = Field(min_length=1)

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class QualityInspectionUpdate(BaseModel):
    inspection_date: date | None = None
    inspector_user_id: UUID | None = None
    notes: str | None = None
    lines: list[QualityInspectionLineInput] | None = Field(default=None, min_length=1)
    version: int | None = Field(default=None, ge=1)

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class QualityInspectionCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class QualityInspectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    status: QualityInspectionStatus
    version: int
    goods_receipt_id: UUID
    inspection_date: date
    inspector_user_id: UUID | None
    notes: str | None
    approved_at: datetime | None
    approved_by: UUID | None
    cancelled_at: datetime | None
    cancelled_by: UUID | None
    cancel_reason: str | None
    available_actions: list[str] = Field(default_factory=list)
    period_locked: bool = False
    lines: list[QualityInspectionLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

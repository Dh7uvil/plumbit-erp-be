"""FX revaluation schemas."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import FxExposureKind, FxRevaluationStatus


class FxRevaluationRunRequest(BaseModel):
    as_of: date
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class FxRevaluationReverseRequest(BaseModel):
    reversal_date: date
    notes: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)


class FxExposureLine(BaseModel):
    exposure_kind: FxExposureKind
    currency_id: UUID
    currency_code: str | None = None
    party_type: str | None = None
    party_id: UUID | None = None
    account_id: UUID
    foreign_balance: Decimal
    closing_rate: Decimal
    book_base: Decimal
    revalued_base: Decimal
    gain_base: Decimal
    source_type: str = "account"
    source_id: UUID | None = None


class FxExposureResponse(BaseModel):
    as_of: date
    currency_code: str
    total_gain_base: Decimal
    lines: list[FxExposureLine] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class FxRevaluationLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    exposure_kind: FxExposureKind
    currency_id: UUID
    currency_code: str | None = None
    party_type: str | None
    party_id: UUID | None
    account_id: UUID
    foreign_balance: Decimal
    closing_rate: Decimal
    book_base: Decimal
    revalued_base: Decimal
    gain_base: Decimal
    source_type: str = "account"
    source_id: UUID | None = None


class FxRevaluationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    as_of_date: date
    status: FxRevaluationStatus
    version: int
    journal_entry_id: UUID | None
    reversal_journal_entry_id: UUID | None
    reversed_at: datetime | None
    total_gain_base: Decimal
    notes: str | None
    warnings: list[str] = Field(default_factory=list)
    lines: list[FxRevaluationLineResponse] = Field(default_factory=list)
    available_actions: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None

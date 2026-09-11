"""Journal entry request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.common.schemas.related_documents import RelatedDocumentRef
from app.core.enums import JournalEntryStatus, JournalType, PartyType


class JournalEntryFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "document_number", "entry_date", "status"}
    )
    status: JournalEntryStatus | None = None
    journal_type: JournalType | None = None
    account_id: UUID | None = None
    party_id: UUID | None = None
    branch_id: UUID | None = None
    entry_date_from: date | None = None
    entry_date_to: date | None = None

    @model_validator(mode="after")
    def validate_entry_date_range(self) -> "JournalEntryFilter":
        if (
            self.entry_date_from is not None
            and self.entry_date_to is not None
            and self.entry_date_from > self.entry_date_to
        ):
            raise ValueError("entry_date_from must be before or equal to entry_date_to")
        return self


class JournalLineInput(BaseModel):
    account_id: UUID
    debit: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    credit: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    currency_id: UUID | None = None
    exchange_rate: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=6)
    party_type: PartyType | None = None
    party_id: UUID | None = None
    due_date: date | None = None
    external_reference: str | None = Field(default=None, max_length=100)
    tax_id: UUID | None = None
    branch_id: UUID | None = None
    description: str | None = Field(default=None, max_length=500)

    @field_validator("external_reference", "description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class JournalLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    account_id: UUID
    debit: Decimal
    credit: Decimal
    debit_base: Decimal
    credit_base: Decimal
    currency_id: UUID
    exchange_rate: Decimal
    party_type: PartyType | None
    party_id: UUID | None
    due_date: date | None
    external_reference: str | None
    tax_id: UUID | None
    branch_id: UUID | None
    description: str | None


class JournalEntryCreate(BaseModel):
    entry_date: date | None = None
    currency_id: UUID | None = None
    exchange_rate: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=6)
    branch_id: UUID | None = None
    narration: str | None = None
    reference: str | None = Field(default=None, max_length=100)
    lines: list[JournalLineInput] = Field(min_length=1)

    @field_validator("narration", "reference")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class JournalEntryUpdate(BaseModel):
    entry_date: date | None = None
    currency_id: UUID | None = None
    exchange_rate: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=6)
    branch_id: UUID | None = None
    narration: str | None = None
    reference: str | None = Field(default=None, max_length=100)
    lines: list[JournalLineInput] | None = Field(default=None, min_length=1)
    version: int | None = Field(default=None, ge=1)

    @field_validator("narration", "reference")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class JournalEntryCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)


class JournalEntryReverseRequest(BaseModel):
    reversal_date: date | None = None
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)


class JournalEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    entry_date: date
    status: JournalEntryStatus
    version: int
    is_posted: bool
    journal_type: JournalType
    source_type: str | None
    source_id: UUID | None
    reversal_of_id: UUID | None
    reversed_by_id: UUID | None
    currency_id: UUID
    exchange_rate: Decimal
    branch_id: UUID | None
    narration: str | None
    reference: str | None
    posted_at: datetime | None
    posted_by: UUID | None
    total_debit_base: Decimal
    total_credit_base: Decimal
    available_actions: list[str] = Field(default_factory=list)
    period_locked: bool = False
    related_documents: list[RelatedDocumentRef] = Field(default_factory=list)
    lines: list[JournalLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

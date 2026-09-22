"""Cheque request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import ChequeDirection, ChequeStatus, PartyType
from app.erp.accounting.open_items.schemas import PaymentAllocationInput


class ChequeFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "created_at",
            "updated_at",
            "cheque_date",
            "due_date",
            "amount",
            "status",
            "cheque_number",
        }
    )
    status: ChequeStatus | None = None
    direction: ChequeDirection | None = None
    bank_account_id: UUID | None = None
    party_id: UUID | None = None
    due_date_from: date | None = None
    due_date_to: date | None = None


class ChequeCreate(BaseModel):
    cheque_number: str = Field(min_length=1, max_length=50)
    direction: ChequeDirection
    cheque_date: date
    due_date: date | None = None
    amount: Decimal = Field(gt=0)
    currency_id: UUID | None = None
    party_type: PartyType | None = None
    party_id: UUID | None = None
    bank_account_id: UUID
    narration: str | None = None
    customer_payment_id: UUID | None = None
    supplier_payment_id: UUID | None = None
    voucher_id: UUID | None = None
    allocations: list[PaymentAllocationInput] = Field(default_factory=list)

    @field_validator("cheque_number")
    @classmethod
    def normalize_number(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("cheque_number is required")
        return normalized


class ChequeUpdate(BaseModel):
    cheque_number: str | None = Field(default=None, min_length=1, max_length=50)
    cheque_date: date | None = None
    due_date: date | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    currency_id: UUID | None = None
    party_type: PartyType | None = None
    party_id: UUID | None = None
    bank_account_id: UUID | None = None
    narration: str | None = None
    allocations: list[PaymentAllocationInput] | None = None
    version: int


class ChequeAllocationResponse(BaseModel):
    id: UUID
    item_type: str
    item_id: UUID
    item_document_number: str | None = None
    amount: Decimal
    journal_entry_id: UUID | None = None
    reversed_at: datetime | None = None
    created_at: datetime | None = None


class ChequeBounceRequest(BaseModel):
    reason: str | None = None
    version: int


class ChequeCancelRequest(BaseModel):
    reason: str | None = None
    version: int


class ChequeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    cheque_number: str
    direction: ChequeDirection
    status: ChequeStatus
    version: int
    is_posted: bool
    cheque_date: date
    due_date: date | None
    amount: Decimal
    amount_unapplied: Decimal
    currency_id: UUID
    base_currency_id: UUID
    exchange_rate: Decimal
    foreign_amount: Decimal
    base_amount: Decimal
    party_type: PartyType | None
    party_id: UUID | None
    bank_account_id: UUID
    customer_payment_id: UUID | None
    supplier_payment_id: UUID | None
    voucher_id: UUID | None
    narration: str | None
    journal_entry_id: UUID | None
    clearing_journal_entry_id: UUID | None
    reversal_journal_entry_id: UUID | None
    clearing_reversal_journal_entry_id: UUID | None = None
    allocations: list[ChequeAllocationResponse] = Field(default_factory=list)
    issued_at: datetime | None
    issued_by: UUID | None
    cleared_at: datetime | None
    cleared_by: UUID | None
    bounced_at: datetime | None
    bounced_by: UUID | None
    bounce_reason: str | None
    available_actions: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None

"""Voucher request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import InvoiceDocumentStatus, PaymentMethod, VoucherType
from app.erp.accounting.open_items.schemas import PaymentAllocationInput


class VoucherFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "created_at",
            "updated_at",
            "document_number",
            "voucher_date",
            "status",
            "total_amount",
        }
    )
    status: InvoiceDocumentStatus | None = None
    voucher_type: VoucherType | None = None
    party_id: UUID | None = None
    currency_id: UUID | None = None
    payment_method: PaymentMethod | None = None
    voucher_date_from: date | None = None
    voucher_date_to: date | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> "VoucherFilter":
        if (
            self.voucher_date_from is not None
            and self.voucher_date_to is not None
            and self.voucher_date_from > self.voucher_date_to
        ):
            raise ValueError("voucher_date_from must be before or equal to voucher_date_to")
        return self


class VoucherLineInput(BaseModel):
    account_id: UUID
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    party_type: str | None = None
    party_id: UUID | None = None
    tax_id: UUID | None = None
    branch_id: UUID | None = None
    cost_center_id: UUID | None = None
    description: str | None = Field(default=None, max_length=255)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class VoucherLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    account_id: UUID
    amount: Decimal
    party_type: str | None
    party_id: UUID | None
    tax_id: UUID | None
    branch_id: UUID | None
    cost_center_id: UUID | None
    description: str | None


_ACTIVE_VOUCHER_TYPES = frozenset(
    {
        VoucherType.CASH_RECEIPT,
        VoucherType.CASH_PAYMENT,
        VoucherType.BANK_RECEIPT,
        VoucherType.BANK_PAYMENT,
    }
)


class VoucherCreate(BaseModel):
    voucher_type: VoucherType
    voucher_date: date | None = None
    payment_account_id: UUID
    counter_account_id: UUID | None = None
    total_amount: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    currency_id: UUID | None = None
    party_type: str | None = None
    party_id: UUID | None = None
    payment_method: PaymentMethod = PaymentMethod.CASH
    reference: str | None = Field(default=None, max_length=100)
    branch_id: UUID | None = None
    cost_center_id: UUID | None = None
    narration: str | None = None
    lines: list[VoucherLineInput] = Field(default_factory=list)
    allocations: list[PaymentAllocationInput] = Field(default_factory=list)

    @field_validator("voucher_type")
    @classmethod
    def reject_contra(cls, value: VoucherType) -> VoucherType:
        if value == VoucherType.CONTRA:
            raise ValueError("Contra vouchers are not supported")
        if value not in _ACTIVE_VOUCHER_TYPES:
            raise ValueError("Unsupported voucher type")
        return value

    @field_validator("reference", "narration")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class VoucherUpdate(BaseModel):
    voucher_date: date | None = None
    payment_account_id: UUID | None = None
    counter_account_id: UUID | None = None
    total_amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    currency_id: UUID | None = None
    party_type: str | None = None
    party_id: UUID | None = None
    payment_method: PaymentMethod | None = None
    reference: str | None = Field(default=None, max_length=100)
    branch_id: UUID | None = None
    cost_center_id: UUID | None = None
    narration: str | None = None
    lines: list[VoucherLineInput] | None = None
    allocations: list[PaymentAllocationInput] | None = None
    version: int | None = Field(default=None, ge=1)

    @field_validator("reference", "narration")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class VoucherResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    display_number: str
    voucher_type: VoucherType
    status: InvoiceDocumentStatus
    version: int
    is_posted: bool
    voucher_date: date
    document_date: date
    payment_account_id: UUID
    counter_account_id: UUID | None
    total_amount: Decimal
    amount_unapplied: Decimal
    currency_id: UUID
    base_currency_id: UUID
    exchange_rate: Decimal
    foreign_amount: Decimal
    base_amount: Decimal
    party_type: str | None
    party_id: UUID | None
    payment_method: PaymentMethod
    reference: str | None
    branch_id: UUID | None
    cost_center_id: UUID | None
    narration: str | None
    journal_entry_id: UUID | None
    reversal_journal_entry_id: UUID | None
    posted_at: datetime | None
    posted_by: UUID | None
    cancelled_at: datetime | None
    cancelled_by: UUID | None
    cancel_reason: str | None
    lines: list[VoucherLineResponse] = Field(default_factory=list)
    allocations: list[PaymentAllocationInput] = Field(default_factory=list)
    available_actions: list[str] = Field(default_factory=list)


class VoucherCancelRequest(BaseModel):
    reason: str | None = None
    version: int = Field(ge=1)

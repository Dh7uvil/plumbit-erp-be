"""Cost sheet request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import (
    ChargeAllocationMethod,
    CostSheetMode,
    CostSheetStatus,
    CostSheetType,
    LedgerLineKind,
)


class CostSheetFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "created_at",
            "updated_at",
            "document_number",
            "document_date",
            "status",
            "sheet_type",
        }
    )
    status: CostSheetStatus | None = None
    sheet_type: CostSheetType | None = None
    shipment_id: UUID | None = None
    purchase_order_id: UUID | None = None
    supplier_id: UUID | None = None
    customer_id: UUID | None = None
    document_date_from: date | None = None
    document_date_to: date | None = None

    @model_validator(mode="after")
    def validate_document_date_range(self) -> "CostSheetFilter":
        if (
            self.document_date_from is not None
            and self.document_date_to is not None
            and self.document_date_from > self.document_date_to
        ):
            raise ValueError("document_date_from must be before or equal to document_date_to")
        return self


class CostSheetLineInput(BaseModel):
    product_id: UUID
    unit_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    base_rate: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    target_selling_price: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=4
    )
    goods_receipt_line_id: UUID | None = None


class CostSheetJournalLineInput(BaseModel):
    line_kind: LedgerLineKind = LedgerLineKind.G
    account_id: UUID | None = None
    party_id: UUID | None = None
    debit: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    credit: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    description: str | None = Field(default=None, max_length=500)
    capitalize: bool = True

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CostSheetChargeInput(BaseModel):
    charge_type_id: UUID
    estimated_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    actual_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    allocation_basis: ChargeAllocationMethod | None = None
    purchase_invoice_id: UUID | None = None
    purchase_invoice_line_id: UUID | None = None


class CostSheetCreate(BaseModel):
    sheet_type: CostSheetType
    sheet_mode: CostSheetMode = CostSheetMode.PLANNING
    purchase_invoice_id: UUID | None = None
    imp_reference: str | None = Field(default=None, max_length=80)
    document_date: date | None = None
    shipment_id: UUID | None = None
    purchase_order_id: UUID | None = None
    supplier_id: UUID | None = None
    customer_id: UUID | None = None
    proforma_invoice_id: UUID | None = None
    currency_id: UUID | None = None
    exchange_rate: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=6)
    incoterm: str | None = Field(default=None, max_length=10)
    port_of_loading: str | None = Field(default=None, max_length=120)
    port_of_discharge: str | None = Field(default=None, max_length=120)
    allocation_method: ChargeAllocationMethod = ChargeAllocationMethod.VALUE
    notes: str | None = None
    lines: list[CostSheetLineInput] = Field(default_factory=list)
    charges: list[CostSheetChargeInput] = Field(default_factory=list)
    journal_lines: list[CostSheetJournalLineInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_mode_lines(self) -> "CostSheetCreate":
        if self.sheet_mode == CostSheetMode.JOURNAL:
            if not self.journal_lines:
                raise ValueError("Journal mode requires at least one journal line")
        elif not self.lines:
            raise ValueError("Planning mode requires at least one product line")
        return self

    @field_validator("notes", "incoterm", "port_of_loading", "port_of_discharge", "imp_reference")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CostSheetUpdate(BaseModel):
    sheet_mode: CostSheetMode | None = None
    purchase_invoice_id: UUID | None = None
    imp_reference: str | None = Field(default=None, max_length=80)
    document_date: date | None = None
    shipment_id: UUID | None = None
    purchase_order_id: UUID | None = None
    supplier_id: UUID | None = None
    customer_id: UUID | None = None
    proforma_invoice_id: UUID | None = None
    currency_id: UUID | None = None
    exchange_rate: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=6)
    incoterm: str | None = Field(default=None, max_length=10)
    port_of_loading: str | None = Field(default=None, max_length=120)
    port_of_discharge: str | None = Field(default=None, max_length=120)
    allocation_method: ChargeAllocationMethod | None = None
    notes: str | None = None
    lines: list[CostSheetLineInput] | None = None
    charges: list[CostSheetChargeInput] | None = None
    journal_lines: list[CostSheetJournalLineInput] | None = None
    version: int | None = Field(default=None, ge=1)

    @field_validator("notes", "incoterm", "port_of_loading", "port_of_discharge", "imp_reference")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CostSheetLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    product_id: UUID
    unit_id: UUID
    quantity: Decimal
    base_rate: Decimal
    target_selling_price: Decimal | None
    goods_receipt_line_id: UUID | None
    line_goods_value: Decimal
    base_amount: Decimal | None = None
    estimated_landed_unit_cost: Decimal
    actual_landed_unit_cost: Decimal | None
    expected_margin_pct: Decimal | None


class CostSheetJournalLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    line_kind: LedgerLineKind
    account_id: UUID | None
    party_id: UUID | None
    debit: Decimal
    credit: Decimal
    description: str | None
    capitalize: bool


class CostSheetChargeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    charge_type_id: UUID
    estimated_amount: Decimal
    actual_amount: Decimal | None
    variance_amount: Decimal | None
    allocation_basis: ChargeAllocationMethod | None
    purchase_invoice_id: UUID | None
    purchase_invoice_line_id: UUID | None
    is_inventoriable: bool = False


class CostSheetTotals(BaseModel):
    goods_value_estimated: Decimal
    inventoriable_charges_estimated: Decimal
    inventoriable_charges_actual: Decimal | None
    expensed_charges_estimated: Decimal
    expensed_charges_actual: Decimal | None
    weighted_landed_unit_cost_estimated: Decimal | None
    weighted_landed_unit_cost_actual: Decimal | None
    fob_total: Decimal | None = None
    cif_total: Decimal | None = None
    reference_selling_total: Decimal | None = None
    sheet_expected_margin_pct: Decimal | None = None


class CostSheetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    sheet_type: CostSheetType
    sheet_mode: CostSheetMode = CostSheetMode.PLANNING
    status: CostSheetStatus
    version: int
    document_date: date
    purchase_invoice_id: UUID | None = None
    imp_reference: str | None = None
    purchase_invoice_number: str | None = None
    journal_entry_id: UUID | None = None
    reversal_journal_entry_id: UUID | None = None
    goods_receipt_charge_adjustment_id: UUID | None = None
    shipment_id: UUID | None
    purchase_order_id: UUID | None
    supplier_id: UUID | None
    customer_id: UUID | None
    proforma_invoice_id: UUID | None
    currency_id: UUID
    base_currency_id: UUID
    exchange_rate: Decimal
    incoterm: str | None
    port_of_loading: str | None
    port_of_discharge: str | None
    allocation_method: ChargeAllocationMethod
    notes: str | None
    totals: CostSheetTotals
    base_total: Decimal | None = None
    available_actions: list[str] = Field(default_factory=list)
    lines: list[CostSheetLineResponse] = Field(default_factory=list)
    charges: list[CostSheetChargeResponse] = Field(default_factory=list)
    journal_lines: list[CostSheetJournalLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None


class CostSheetVersionRequest(BaseModel):
    version: int | None = Field(default=None, ge=1)

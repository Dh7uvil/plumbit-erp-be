"""Print DTO shared by commercial documents. Frontend renders; no PDF worker."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class PrintLetterhead(BaseModel):
    company_name: str
    company_code: str
    trn: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    address: str | None = None
    logo_url: str | None = None
    bank_details: str | None = None
    default_currency: str | None = None


class PrintJournalLine(BaseModel):
    line_number: int
    account_code: str | None = None
    account_name: str
    description: str | None = None
    debit: Decimal | None = None
    credit: Decimal | None = None


class PrintLine(BaseModel):
    line_number: int
    item_code: str | None = None
    description: str
    packing_unit: str | None = None
    carton_qty: Decimal | None = None
    quantity: Decimal
    unit_price: Decimal | None = None
    taxable_amount: Decimal | None = None
    tax_rate: Decimal | None = None
    tax_amount: Decimal | None = None
    amount: Decimal | None = None
    cbm: Decimal | None = None
    weight: Decimal | None = None
    remarks: str | None = None


class PrintDocumentResponse(BaseModel):
    document_type: str
    document_id: UUID
    document_number: str
    document_date: date
    template_family: str = "uae"
    template_kind: str = "commercial"
    voucher_type: str | None = None
    payment_method: str | None = None
    party_name: str | None = None
    party_code: str | None = None
    cheque_number: str | None = None
    cheque_date: date | None = None
    due_date: date | None = None
    narration: str | None = None
    reference: str | None = None
    customer_code: str | None = None
    customer_name: str | None = None
    customer_address: str | None = None
    customer_trn: str | None = None
    lpo_number: str | None = None
    delivery_note_number: str | None = None
    invoice_number: str | None = None
    bl_number: str | None = None
    container_number: str | None = None
    incoterm: str | None = None
    incoterm_place: str | None = None
    currency_code: str | None = None
    subtotal: Decimal | None = None
    tax_amount: Decimal | None = None
    grand_total: Decimal | None = None
    amount_in_words: str | None = None
    payment_terms: str | None = None
    notes: str | None = None
    letterhead: PrintLetterhead
    lines: list[PrintLine] = Field(default_factory=list)
    journal_lines: list[PrintJournalLine] = Field(default_factory=list)

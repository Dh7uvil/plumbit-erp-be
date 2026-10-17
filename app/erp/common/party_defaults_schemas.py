"""Compose-default schemas for party-driven document headers."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.core.enums import PlaceOfSupply, TaxTreatment


class CustomerDocumentComposeDefaults(BaseModel):
    customer_id: UUID
    customer_name: str
    customer_trn: str | None
    tax_treatment: TaxTreatment
    currency_id: UUID
    price_list_id: UUID | None = None
    payment_terms_id: UUID | None
    salesperson_id: UUID | None
    contact_id: UUID | None
    warehouse_id: UUID | None
    place_of_supply: PlaceOfSupply
    bill_to_snapshot: str | None
    ship_to_snapshot: str | None
    terms_and_conditions: str | None


class SupplierDocumentComposeDefaults(BaseModel):
    supplier_id: UUID
    supplier_name: str
    supplier_trn: str | None
    tax_treatment: TaxTreatment
    currency_id: UUID
    payment_terms_id: UUID | None
    contact_id: UUID | None
    warehouse_id: UUID | None
    place_of_supply: PlaceOfSupply
    supplier_address_snapshot: str | None
    deliver_to_snapshot: str | None
    terms_and_conditions: str | None
    freight_forwarder_id: UUID | None = None


class CustomerPaymentComposeDefaults(BaseModel):
    customer_id: UUID
    currency_id: UUID
    receivable_account_id: UUID | None


class SupplierPaymentComposeDefaults(BaseModel):
    supplier_id: UUID
    currency_id: UUID
    payable_account_id: UUID | None


class ProductLineDefaults(BaseModel):
    unit_id: UUID | None
    tax_id: UUID | None
    rate: str | None
    available_qty: str | None = None
    average_cost: str | None = None

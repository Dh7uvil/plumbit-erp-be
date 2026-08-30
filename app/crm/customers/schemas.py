"""Customer schemas."""

from datetime import datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.auth.schemas import AddressPayload, AddressResponse
from app.common.schemas.filters import BaseFilter
from app.common.utils.validators import normalize_required_text
from app.core.enums import CompanyType, TaxTreatment


class CustomerFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "name", "code"}
    )
    tax_treatment: TaxTreatment | None = None
    currency_id: UUID | None = None
    company_type: CompanyType | None = None
    is_active: bool | None = None


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=50)
    company_type: CompanyType = CompanyType.CUSTOMER
    trn: str | None = Field(default=None, max_length=50)
    tax_treatment: TaxTreatment
    currency_id: UUID | None = None
    default_price_list_id: UUID | None = None
    payment_terms_id: UUID | None = None
    credit_limit: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    salesperson_id: UUID | None = None
    billing_address: AddressPayload | None = None
    shipping_address: AddressPayload | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return normalize_required_text(value, field_name="code").upper()

    @field_validator("trn")
    @classmethod
    def normalize_trn(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def require_trn_when_registered(self) -> "CustomerCreate":
        if self.tax_treatment == TaxTreatment.REGISTERED and not self.trn:
            raise ValueError("TRN is required when tax treatment is REGISTERED")
        return self


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    company_type: CompanyType | None = None
    trn: str | None = Field(default=None, max_length=50)
    tax_treatment: TaxTreatment | None = None
    currency_id: UUID | None = None
    default_price_list_id: UUID | None = None
    payment_terms_id: UUID | None = None
    credit_limit: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    salesperson_id: UUID | None = None
    billing_address: AddressPayload | None = None
    shipping_address: AddressPayload | None = None
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")

    @field_validator("trn")
    @classmethod
    def normalize_trn(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CustomerExtraAddressCreate(BaseModel):
    label: str | None = Field(default=None, max_length=100)
    address: AddressPayload
    is_default_billing: bool = False
    is_default_shipping: bool = False


class CustomerExtraAddressResponse(BaseModel):
    id: UUID
    label: str | None
    is_default_billing: bool
    is_default_shipping: bool
    address: AddressResponse


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    code: str
    company_type: CompanyType
    trn: str | None
    tax_treatment: TaxTreatment
    currency_id: UUID
    default_price_list_id: UUID | None
    payment_terms_id: UUID | None
    credit_limit: Decimal | None
    salesperson_id: UUID | None
    billing_address: AddressResponse | None = None
    shipping_address: AddressResponse | None = None
    extra_addresses: list[CustomerExtraAddressResponse] = Field(default_factory=list)
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

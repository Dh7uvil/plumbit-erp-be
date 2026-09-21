"""Lead request and response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import LeadStatus, TaxTreatment


class LeadFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "created_at",
            "updated_at",
            "lead_number",
            "status",
            "first_name",
            "last_name",
            "company_name",
        }
    )
    status: LeadStatus | None = None
    source_id: UUID | None = None
    owner_id: UUID | None = None
    rating: str | None = None
    campaign_id: UUID | None = None


class LeadCreate(BaseModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    company_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    title: str | None = Field(default=None, max_length=100)
    rating: str | None = Field(default=None, max_length=20)
    source_id: UUID | None = None
    owner_id: UUID | None = None
    campaign_id: UUID | None = None
    estimated_value: Decimal | None = Field(default=None, ge=0)
    currency_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("first_name", "last_name", "company_name", "title")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if "@" not in normalized:
            raise ValueError("email must be a valid email address")
        return normalized

    @field_validator("phone", "rating")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def require_identity(self) -> Self:
        if not self.first_name and not self.last_name and not self.company_name:
            raise ValueError("Provide at least a first name, last name, or company name")
        if (self.estimated_value is None) != (self.currency_id is None):
            raise ValueError("estimated_value and currency_id must be provided together")
        return self


class LeadUpdate(BaseModel):
    version: int | None = Field(default=None, ge=1)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    company_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    title: str | None = Field(default=None, max_length=100)
    rating: str | None = Field(default=None, max_length=20)
    source_id: UUID | None = None
    owner_id: UUID | None = None
    campaign_id: UUID | None = None
    estimated_value: Decimal | None = Field(default=None, ge=0)
    currency_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("first_name", "last_name", "company_name", "title")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if "@" not in normalized:
            raise ValueError("email must be a valid email address")
        return normalized

    @field_validator("phone", "rating")
    @classmethod
    def normalize_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class LeadAssign(BaseModel):
    owner_id: UUID
    version: int | None = Field(default=None, ge=1)


class LeadStatusChange(BaseModel):
    status: LeadStatus
    version: int | None = Field(default=None, ge=1)


class LeadConvertCustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    tax_treatment: TaxTreatment = TaxTreatment.UNREGISTERED
    currency_id: UUID | None = None
    trn: str | None = Field(default=None, max_length=50)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @field_validator("trn")
    @classmethod
    def normalize_trn(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def require_trn_when_registered(self) -> Self:
        if self.tax_treatment == TaxTreatment.REGISTERED and not self.trn:
            raise ValueError("TRN is required when tax treatment is REGISTERED")
        return self


class LeadConvertContact(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    is_primary: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if "@" not in normalized:
            raise ValueError("email must be a valid email address")
        return normalized

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class LeadConvertOpportunity(BaseModel):
    create: bool = True
    name: str | None = Field(default=None, min_length=1, max_length=200)
    pipeline_id: UUID | None = None
    stage_id: UUID | None = None
    amount: Decimal | None = Field(default=None, ge=0)
    currency_id: UUID | None = None
    expected_close_date: date | None = None
    owner_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized

    @model_validator(mode="after")
    def amount_requires_currency(self) -> Self:
        if (self.amount is None) != (self.currency_id is None):
            raise ValueError("amount and currency_id must be provided together")
        return self


class LeadConvert(BaseModel):
    version: int | None = Field(default=None, ge=1)
    customer_id: UUID | None = None
    new_customer: LeadConvertCustomerCreate | None = None
    contact: LeadConvertContact
    opportunity: LeadConvertOpportunity | None = None

    @model_validator(mode="after")
    def require_customer_source(self) -> Self:
        if (self.customer_id is None) == (self.new_customer is None):
            raise ValueError("Provide exactly one of customer_id or new_customer")
        return self


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    lead_number: str
    first_name: str | None
    last_name: str | None
    company_name: str | None
    email: str | None
    phone: str | None
    title: str | None
    status: LeadStatus
    rating: str | None
    source_id: UUID | None
    owner_id: UUID | None
    campaign_id: UUID | None
    estimated_value: Decimal | None
    currency_id: UUID | None
    notes: str | None
    version: int
    converted_customer_id: UUID | None
    converted_contact_id: UUID | None
    converted_opportunity_id: UUID | None
    converted_at: datetime | None
    available_actions: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None

    @property
    def display_name(self) -> str:
        parts = [part for part in (self.first_name, self.last_name) if part]
        if parts:
            name = " ".join(parts)
            if self.company_name:
                return f"{name} ({self.company_name})"
            return name
        return self.company_name or self.lead_number


class LeadConvertResponse(BaseModel):
    lead: LeadResponse
    customer_id: UUID
    contact_id: UUID
    opportunity_id: UUID | None

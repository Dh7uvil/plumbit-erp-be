"""Chart of accounts request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.schemas.filters import BaseFilter
from app.common.utils.validators import normalize_required_text
from app.core.enums import AccountSubtype, AccountSystemRole, AccountType


class AccountFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "code", "name", "account_type", "depth"}
    )
    account_type: AccountType | None = None
    account_subtype: AccountSubtype | None = None
    is_group: bool | None = None
    is_active: bool | None = None


class AccountCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    account_type: AccountType
    account_subtype: AccountSubtype
    parent_id: UUID | None = None
    is_group: bool = False
    is_blocked: bool = False
    currency_id: UUID | None = None
    default_tax_id: UUID | None = None
    financial_category_id: UUID | None = None

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return normalize_required_text(value, field_name="code")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class AccountUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=20)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    account_type: AccountType | None = None
    account_subtype: AccountSubtype | None = None
    parent_id: UUID | None = None
    is_group: bool | None = None
    is_active: bool | None = None
    is_blocked: bool | None = None
    currency_id: UUID | None = None
    default_tax_id: UUID | None = None
    financial_category_id: UUID | None = None

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="code")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    code: str
    name: str
    description: str | None
    account_type: AccountType
    account_subtype: AccountSubtype
    parent_id: UUID | None
    parent_code: str | None = None
    parent_name: str | None = None
    depth: int
    is_group: bool
    is_system: bool
    system_role: AccountSystemRole | None
    currency_id: UUID | None
    default_tax_id: UUID | None = None
    financial_category_id: UUID | None = None
    default_tax_rate: Decimal | None = None
    financial_category_name: str | None = None
    is_active: bool
    is_blocked: bool = False
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None
    has_children: bool = False
    has_journal_lines: bool = False


class AccountBalanceResponse(BaseModel):
    account_id: UUID
    as_of: date
    debit: Decimal
    credit: Decimal
    signed_balance: Decimal
    currency_code: str | None = None


class AccountPeriodBalance(BaseModel):
    period: int
    from_date: date
    to_date: date
    debit: Decimal
    credit: Decimal
    closing: Decimal


class AccountPeriodBalancesResponse(BaseModel):
    account_id: UUID
    fiscal_year: int
    currency_code: str
    opening: Decimal
    periods: list[AccountPeriodBalance]
    closing: Decimal


class AccountTreeNode(AccountResponse):
    children: list["AccountTreeNode"] = Field(default_factory=list)


class SystemRoleMapping(BaseModel):
    role: AccountSystemRole
    account_id: UUID | None
    account_code: str | None = None
    account_name: str | None = None


class SystemRoleUpdate(BaseModel):
    account_id: UUID

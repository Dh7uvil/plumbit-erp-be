"""Supplier schemas."""

from typing import ClassVar
from uuid import UUID

from app.common.schemas.filters import BaseFilter
from app.core.enums import CompanyType, TaxTreatment
from app.crm.customers.schemas import (
    CustomerCreate,
    CustomerExtraAddressCreate,
    CustomerExtraAddressResponse,
    CustomerResponse,
    CustomerUpdate,
)


class SupplierFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "name", "code"}
    )
    tax_treatment: TaxTreatment | None = None
    currency_id: UUID | None = None
    is_active: bool | None = None


class SupplierCreate(CustomerCreate):
    company_type: CompanyType = CompanyType.SUPPLIER


class SupplierUpdate(CustomerUpdate):
    pass


class SupplierExtraAddressCreate(CustomerExtraAddressCreate):
    pass


class SupplierExtraAddressResponse(CustomerExtraAddressResponse):
    pass


class SupplierResponse(CustomerResponse):
    pass

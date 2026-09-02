"""Customer use cases."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import CRM_MODULE, ERP_MODULE
from app.auth.org_service import OrganizationService
from app.auth.schemas import AddressPayload, AddressResponse, format_address_label
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.core.enums import AddressType, AuditAction, CompanyType, TaxTreatment
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError, ValidationError
from app.crm.customers.models import Customer, CustomerAddress
from app.crm.customers.repository import CustomerRepository
from app.crm.customers.schemas import (
    CustomerCreate,
    CustomerExtraAddressCreate,
    CustomerExtraAddressResponse,
    CustomerResponse,
    CustomerUpdate,
)
from app.db.session import transaction
from app.erp.accounting.service import PaymentTermService
from app.erp.exchange_rates.service import CurrencyService
from app.inventory_management.price_lists.service import PriceListService


@dataclass(frozen=True, slots=True)
class PartyRole:
    visible_types: frozenset[CompanyType]
    allowed_write_types: frozenset[CompanyType]
    default_create_type: CompanyType
    not_found_message: str
    duplicate_code_message: str
    extra_address_not_found_message: str
    audit_module: str
    audit_entity_type: str


CUSTOMER_PARTY_ROLE = PartyRole(
    visible_types=frozenset({CompanyType.CUSTOMER, CompanyType.BOTH, CompanyType.OTHER}),
    allowed_write_types=frozenset({CompanyType.CUSTOMER, CompanyType.BOTH, CompanyType.OTHER}),
    default_create_type=CompanyType.CUSTOMER,
    not_found_message="Customer not found",
    duplicate_code_message="A customer with this code already exists",
    extra_address_not_found_message="Customer address not found",
    audit_module=CRM_MODULE,
    audit_entity_type="customer",
)


SUPPLIER_PARTY_ROLE = PartyRole(
    visible_types=frozenset({CompanyType.SUPPLIER, CompanyType.BOTH}),
    allowed_write_types=frozenset({CompanyType.SUPPLIER, CompanyType.BOTH}),
    default_create_type=CompanyType.SUPPLIER,
    not_found_message="Supplier not found",
    duplicate_code_message="A supplier with this code already exists",
    extra_address_not_found_message="Supplier address not found",
    audit_module=ERP_MODULE,
    audit_entity_type="supplier",
)


class CustomerService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        role: PartyRole = CUSTOMER_PARTY_ROLE,
        repo: CustomerRepository | None = None,
    ) -> None:
        self.session = session
        self.role = role
        self.repo = repo or CustomerRepository(session)
        self.org = OrganizationService(session)
        self.currencies = CurrencyService(session)
        self.price_lists = PriceListService(session)
        self.payment_terms = PaymentTermService(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        tax_treatment: str | None = None,
        currency_id: UUID | None = None,
        company_type: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[CustomerResponse], int]:
        filters: dict[str, object] = {}
        if tax_treatment is not None:
            filters["tax_treatment"] = tax_treatment
        if currency_id is not None:
            filters["currency_id"] = currency_id
        filters["company_type"] = self._visible_company_type_filter(company_type)
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        responses = [await self._to_response(tenant_id, row) for row in rows]
        return responses, total

    async def get(self, tenant_id: UUID, customer_id: UUID) -> CustomerResponse:
        row = await self._require(tenant_id, customer_id)
        return await self._to_response(tenant_id, row)

    async def create(
        self, tenant_id: UUID, payload: CustomerCreate, *, actor_user_id: UUID
    ) -> CustomerResponse:
        async with transaction(self.session):
            currency_id = payload.currency_id
            if currency_id is None:
                currency_id = (await self.currencies.get_base(tenant_id)).id
            else:
                await self.currencies.require_id(tenant_id, currency_id)
            self._assert_writable(payload.company_type)
            await self._validate_refs(
                tenant_id,
                price_list_id=payload.default_price_list_id,
                payment_terms_id=payload.payment_terms_id,
                salesperson_id=payload.salesperson_id,
            )
            billing_id = await self.org.upsert_address(
                tenant_id,
                None,
                payload.billing_address,
                address_type=AddressType.BILLING,
            )
            shipping_id = await self.org.upsert_address(
                tenant_id,
                None,
                payload.shipping_address,
                address_type=AddressType.SHIPPING,
            )
            try:
                row = await self.repo.create(
                    tenant_id,
                    {
                        "name": payload.name,
                        "code": payload.code,
                        "company_type": payload.company_type.value,
                        "trn": payload.trn,
                        "tax_treatment": payload.tax_treatment.value,
                        "currency_id": currency_id,
                        "default_price_list_id": payload.default_price_list_id,
                        "payment_terms_id": payload.payment_terms_id,
                        "credit_limit": payload.credit_limit,
                        "salesperson_id": payload.salesperson_id,
                        "billing_address_id": billing_id,
                        "shipping_address_id": shipping_id,
                        "notes": payload.notes,
                        "created_by": actor_user_id,
                        "updated_by": actor_user_id,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError(self.role.duplicate_code_message) from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=self.role.audit_module,
                entity_type=self.role.audit_entity_type,
                entity_id=row.id,
                new_values=await self._customer_snapshot(tenant_id, row),
            )
            return await self._to_response(tenant_id, row)

    async def update(
        self, tenant_id: UUID, customer_id: UUID, payload: CustomerUpdate, *, actor_user_id: UUID
    ) -> CustomerResponse:
        values = payload.model_dump(exclude_unset=True)
        billing_payload = values.pop("billing_address", None)
        shipping_payload = values.pop("shipping_address", None)
        if "tax_treatment" in values and values["tax_treatment"] is not None:
            values["tax_treatment"] = str(values["tax_treatment"])
        if "company_type" in values:
            if values["company_type"] is None:
                raise ValidationError("company_type cannot be null")
            requested = CompanyType(str(values["company_type"]))
            self._assert_writable(requested)
            values["company_type"] = requested.value
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            row = await self._require(tenant_id, customer_id)
            old_values = await self._customer_snapshot(tenant_id, row)
            treatment = TaxTreatment(values.get("tax_treatment", row.tax_treatment))
            trn = values.get("trn", row.trn)
            if treatment == TaxTreatment.REGISTERED and not trn:
                raise ValidationError("TRN is required when tax treatment is REGISTERED")
            if values.get("currency_id") is not None:
                await self.currencies.require_id(tenant_id, values["currency_id"])
            await self._validate_refs(
                tenant_id,
                price_list_id=values.get("default_price_list_id", row.default_price_list_id),
                payment_terms_id=values.get("payment_terms_id", row.payment_terms_id),
                salesperson_id=values.get("salesperson_id", row.salesperson_id),
            )
            if billing_payload is not None:
                values["billing_address_id"] = await self.org.upsert_address(
                    tenant_id,
                    row.billing_address_id,
                    AddressPayload.model_validate(billing_payload),
                    address_type=AddressType.BILLING,
                )
            if shipping_payload is not None:
                values["shipping_address_id"] = await self.org.upsert_address(
                    tenant_id,
                    row.shipping_address_id,
                    AddressPayload.model_validate(shipping_payload),
                    address_type=AddressType.SHIPPING,
                )
            try:
                updated = await self.repo.update(tenant_id, customer_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError(self.role.duplicate_code_message) from exc
            if updated is None:
                raise ResourceNotFoundError(self.role.not_found_message)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=self.role.audit_module,
                entity_type=self.role.audit_entity_type,
                entity_id=updated.id,
                old_values=old_values,
                new_values=await self._customer_snapshot(tenant_id, updated),
            )
            return await self._to_response(tenant_id, updated)

    async def delete(
        self, tenant_id: UUID, customer_id: UUID, *, actor_user_id: UUID
    ) -> CustomerResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, customer_id)
            response = await self._to_response(tenant_id, row)
            await self.repo.soft_delete(tenant_id, customer_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=self.role.audit_module,
                entity_type=self.role.audit_entity_type,
                entity_id=customer_id,
                old_values=await self._customer_snapshot(tenant_id, row),
            )
            return response

    async def add_extra_address(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        payload: CustomerExtraAddressCreate,
        *,
        actor_user_id: UUID,
    ) -> CustomerExtraAddressResponse:
        async with transaction(self.session):
            await self._require(tenant_id, customer_id)
            address_id = await self.org.upsert_address(
                tenant_id,
                None,
                payload.address,
                address_type=AddressType.OTHER,
            )
            if address_id is None:
                raise ValidationError("Address details are required")
            extra = await self.repo.create_extra_address(
                tenant_id,
                {
                    "customer_id": customer_id,
                    "address_id": address_id,
                    "label": payload.label,
                    "is_default_billing": payload.is_default_billing,
                    "is_default_shipping": payload.is_default_shipping,
                },
            )
            address = await self.org.get_address(tenant_id, address_id)
            assert address is not None
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=self.role.audit_module,
                entity_type=self.role.audit_entity_type,
                entity_id=customer_id,
                new_values=self._extra_address_snapshot(extra, address),
            )
            return CustomerExtraAddressResponse(
                id=extra.id,
                label=extra.label,
                is_default_billing=extra.is_default_billing,
                is_default_shipping=extra.is_default_shipping,
                address=address,
            )

    async def delete_extra_address(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        extra_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> CustomerExtraAddressResponse:
        async with transaction(self.session):
            await self._require(tenant_id, customer_id)
            extra = await self.repo.get_extra_address(tenant_id, customer_id, extra_id)
            if extra is None:
                raise ResourceNotFoundError(self.role.extra_address_not_found_message)
            address = await self.org.get_address(tenant_id, extra.address_id)
            await self.repo.soft_delete_extra_address(tenant_id, extra.id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=self.role.audit_module,
                entity_type=self.role.audit_entity_type,
                entity_id=customer_id,
                old_values=self._extra_address_snapshot(extra, address),
            )
            return CustomerExtraAddressResponse(
                id=extra.id,
                label=extra.label,
                is_default_billing=extra.is_default_billing,
                is_default_shipping=extra.is_default_shipping,
                address=address
                or AddressResponse(
                    id=extra.address_id,
                    address_line_1=None,
                    address_line_2=None,
                    city=None,
                    state=None,
                    country=None,
                    country_code=None,
                    postal_code=None,
                ),
            )

    async def _customer_snapshot(self, tenant_id: UUID, row: Customer) -> dict[str, object]:
        currency = await self.currencies.get(tenant_id, row.currency_id)
        price_list_name: str | None = None
        if row.default_price_list_id is not None:
            price_list = await self.price_lists.get(tenant_id, row.default_price_list_id)
            price_list_name = price_list.name
        payment_term_name: str | None = None
        if row.payment_terms_id is not None:
            payment_term = await self.payment_terms.get(tenant_id, row.payment_terms_id)
            payment_term_name = payment_term.name
        addresses = await self.org.get_addresses(
            tenant_id,
            [item for item in (row.billing_address_id, row.shipping_address_id) if item],
        )
        snapshot: dict[str, object] = {
            "name": row.name,
            "code": row.code,
            "company_type": row.company_type,
            "trn": row.trn,
            "tax_treatment": row.tax_treatment,
            "currency": currency.code,
            "price_list": price_list_name,
            "payment_terms": payment_term_name,
            "credit_limit": row.credit_limit,
            "salesperson": await self.org.employee_audit_label(tenant_id, row.salesperson_id),
            "notes": row.notes,
            "is_active": row.is_active,
        }
        billing = format_address_label(
            addresses.get(row.billing_address_id) if row.billing_address_id else None
        )
        shipping = format_address_label(
            addresses.get(row.shipping_address_id) if row.shipping_address_id else None
        )
        if billing is not None:
            snapshot["billing_address"] = billing
        if shipping is not None:
            snapshot["shipping_address"] = shipping
        return snapshot

    @staticmethod
    def _extra_address_snapshot(
        extra: CustomerAddress, address: AddressResponse | None
    ) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "label": extra.label,
            "is_default_billing": extra.is_default_billing,
            "is_default_shipping": extra.is_default_shipping,
        }
        formatted = format_address_label(address)
        if formatted is not None:
            snapshot["address"] = formatted
        return snapshot

    async def _validate_refs(
        self,
        tenant_id: UUID,
        *,
        price_list_id: UUID | None,
        payment_terms_id: UUID | None,
        salesperson_id: UUID | None,
    ) -> None:
        if price_list_id is not None:
            await self.price_lists.require_id(tenant_id, price_list_id)
        if payment_terms_id is not None:
            await self.payment_terms.require_id(tenant_id, payment_terms_id)
        if salesperson_id is not None:
            await self.org.require_employee(tenant_id, salesperson_id)

    async def _to_response(self, tenant_id: UUID, row: Customer) -> CustomerResponse:
        addresses = await self.org.get_addresses(
            tenant_id,
            [item for item in (row.billing_address_id, row.shipping_address_id) if item],
        )
        extras = await self.repo.list_extra_addresses(tenant_id, row.id)
        extra_address_ids = [item.address_id for item in extras]
        extra_addresses = await self.org.get_addresses(tenant_id, extra_address_ids)
        return CustomerResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            name=row.name,
            code=row.code,
            company_type=CompanyType(row.company_type),
            trn=row.trn,
            tax_treatment=TaxTreatment(row.tax_treatment),
            currency_id=row.currency_id,
            default_price_list_id=row.default_price_list_id,
            payment_terms_id=row.payment_terms_id,
            credit_limit=row.credit_limit,
            salesperson_id=row.salesperson_id,
            billing_address=addresses.get(row.billing_address_id)
            if row.billing_address_id
            else None,
            shipping_address=addresses.get(row.shipping_address_id)
            if row.shipping_address_id
            else None,
            extra_addresses=[
                CustomerExtraAddressResponse(
                    id=item.id,
                    label=item.label,
                    is_default_billing=item.is_default_billing,
                    is_default_shipping=item.is_default_shipping,
                    address=extra_addresses[item.address_id],
                )
                for item in extras
                if item.address_id in extra_addresses
            ],
            notes=row.notes,
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _visible_company_type_filter(self, company_type: str | None) -> object:
        visible = tuple(item.value for item in self.role.visible_types)
        if company_type is None:
            return visible
        if company_type in visible:
            return company_type
        return ()

    def _assert_writable(self, company_type: CompanyType) -> None:
        if company_type not in self.role.allowed_write_types:
            allowed = ", ".join(sorted(item.value for item in self.role.allowed_write_types))
            raise ValidationError(f"company_type must be one of: {allowed}")

    async def require_party(self, tenant_id: UUID, party_id: UUID) -> Customer:
        row = await self.repo.get(tenant_id, party_id)
        if row is None:
            raise ResourceNotFoundError("Customer not found")
        return row

    async def _require(self, tenant_id: UUID, customer_id: UUID) -> Customer:
        row = await self.repo.get(tenant_id, customer_id)
        if row is None or CompanyType(row.company_type) not in self.role.visible_types:
            raise ResourceNotFoundError(self.role.not_found_message)
        return row

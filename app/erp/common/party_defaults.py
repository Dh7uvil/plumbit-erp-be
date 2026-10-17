"""Load party-driven compose defaults for commercial documents."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.utils.document_totals import format_address_snapshot, place_of_supply_from_address
from app.crm.contacts.service import ContactService
from app.crm.customers.service import CustomerService
from app.erp.accounting.service import TermsTemplateService
from app.erp.common.party_defaults_schemas import (
    CustomerDocumentComposeDefaults,
    CustomerPaymentComposeDefaults,
    ProductLineDefaults,
    SupplierDocumentComposeDefaults,
    SupplierPaymentComposeDefaults,
)
from app.erp.suppliers.service import SupplierService
from app.inventory_management.price_lists.service import PriceListService
from app.inventory_management.products.service import ProductService
from app.inventory_management.stock.availability import available_qty
from app.inventory_management.stock.repository import StockBalanceRepository
from app.inventory_management.warehouses.service import WarehouseService


class PartyDefaultsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.customers = CustomerService(session)
        self.suppliers = SupplierService(session)
        self.contacts = ContactService(session)
        self.terms = TermsTemplateService(session)
        self.warehouses = WarehouseService(session)
        self.products = ProductService(session)
        self.price_lists = PriceListService(session)

    async def customer_document_defaults(
        self, tenant_id: UUID, customer_id: UUID, *, include_price_list: bool = True
    ) -> CustomerDocumentComposeDefaults:
        customer = await self.customers.get(tenant_id, customer_id)
        primary = await self.contacts.get_primary(tenant_id, customer_id)
        default_terms = await self.terms.get_default(tenant_id)
        default_warehouse = await self.warehouses.get_default(tenant_id)
        place = place_of_supply_from_address(customer.shipping_address)
        return CustomerDocumentComposeDefaults(
            customer_id=customer.id,
            customer_name=customer.name,
            customer_trn=customer.trn,
            tax_treatment=customer.tax_treatment,
            currency_id=customer.currency_id,
            price_list_id=customer.default_price_list_id if include_price_list else None,
            payment_terms_id=customer.payment_terms_id,
            salesperson_id=customer.salesperson_id,
            contact_id=primary.id if primary else None,
            warehouse_id=default_warehouse.id if default_warehouse else None,
            place_of_supply=place,
            bill_to_snapshot=format_address_snapshot(customer.billing_address),
            ship_to_snapshot=format_address_snapshot(customer.shipping_address),
            terms_and_conditions=default_terms.body if default_terms else None,
        )

    async def supplier_document_defaults(
        self, tenant_id: UUID, supplier_id: UUID
    ) -> SupplierDocumentComposeDefaults:
        supplier = await self.suppliers.get(tenant_id, supplier_id)
        primary = await self.contacts.get_primary(tenant_id, supplier_id)
        default_terms = await self.terms.get_default(tenant_id)
        default_warehouse = await self.warehouses.get_default(tenant_id)
        address = supplier.shipping_address or supplier.billing_address
        place = place_of_supply_from_address(address)
        deliver_to = None
        if default_warehouse is not None:
            deliver_to = format_address_snapshot(default_warehouse.address)
        return SupplierDocumentComposeDefaults(
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            supplier_trn=supplier.trn,
            tax_treatment=supplier.tax_treatment,
            currency_id=supplier.currency_id,
            payment_terms_id=supplier.payment_terms_id,
            contact_id=primary.id if primary else None,
            warehouse_id=default_warehouse.id if default_warehouse else None,
            place_of_supply=place,
            supplier_address_snapshot=format_address_snapshot(
                supplier.billing_address or supplier.shipping_address
            ),
            deliver_to_snapshot=deliver_to,
            terms_and_conditions=default_terms.body if default_terms else None,
            freight_forwarder_id=None,
        )

    async def customer_payment_defaults(
        self, tenant_id: UUID, customer_id: UUID
    ) -> CustomerPaymentComposeDefaults:
        customer = await self.customers.get(tenant_id, customer_id)
        return CustomerPaymentComposeDefaults(
            customer_id=customer.id,
            currency_id=customer.currency_id,
            receivable_account_id=customer.receivable_account_id,
        )

    async def supplier_payment_defaults(
        self, tenant_id: UUID, supplier_id: UUID
    ) -> SupplierPaymentComposeDefaults:
        supplier = await self.suppliers.get(tenant_id, supplier_id)
        return SupplierPaymentComposeDefaults(
            supplier_id=supplier.id,
            currency_id=supplier.currency_id,
            payable_account_id=supplier.payable_account_id,
        )

    async def product_line_defaults(
        self,
        tenant_id: UUID,
        product_id: UUID,
        *,
        warehouse_id: UUID | None = None,
        price_list_id: UUID | None = None,
        currency_id: UUID | None = None,
        purchase_side: bool = False,
    ) -> ProductLineDefaults:
        product = await self.products.get(tenant_id, product_id)
        rate: Decimal | None = None
        base = product.purchase_rate if purchase_side else product.selling_rate
        if base is not None:
            rate = await self.price_lists.resolve_rate(
                tenant_id,
                product_id=product_id,
                selling_rate=base,
                price_list_id=price_list_id,
                line_override=None,
                currency_id=currency_id,
            )
        else:
            rate = None

        qty: Decimal | None = None
        if warehouse_id is not None:
            balance = await StockBalanceRepository(self.session).get_for_update(
                tenant_id, warehouse_id, product_id
            )
            if balance is not None:
                qty = available_qty(
                    balance.qty_on_hand, balance.qty_reserved, balance.qty_quality_hold
                )
            else:
                qty = Decimal("0")

        cost: Decimal | None = product.purchase_rate if purchase_side else product.selling_rate

        def _fmt(value: Decimal | None) -> str | None:
            if value is None:
                return None
            return format(value, "f")

        return ProductLineDefaults(
            unit_id=product.unit_id,
            tax_id=product.tax_id,
            rate=_fmt(rate),
            available_qty=_fmt(qty),
            average_cost=_fmt(cost) if cost is not None else None,
        )

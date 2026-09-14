"""Shared ILIKE search helpers, including related-entity EXISTS matches."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import exists, literal, or_, select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.db.base import Base

_ILIKE_ESCAPE = "\\"


@dataclass(frozen=True, slots=True)
class RelatedSearch:
    """Match list rows when a related entity's text fields contain the search term.

    Direct FK (parent.customer_id → Customer.id):
        RelatedSearch(Customer, local_key="customer_id", fields={"name", "code"})

    Child table (parent.id ← Line.sales_order_id), optionally into a product:
        RelatedSearch(
            Line,
            local_key="id",
            remote_key="sales_order_id",
            fields={"description"},
            nested=(RelatedSearch(Product, local_key="product_id", fields={"sku", "name"}),),
        )
    """

    model: type[Base]
    local_key: str
    fields: frozenset[str] = frozenset()
    remote_key: str = "id"
    nested: tuple[RelatedSearch, ...] = ()
    equals: tuple[tuple[str, str], ...] = ()
    null_keys: tuple[str, ...] = ()


def mapped_column(model: type[Any], name: str) -> InstrumentedAttribute[Any]:
    """Return a mapped column or raise if ``name`` is not an instrumented attribute."""

    column = getattr(model, name, None)
    if not isinstance(column, InstrumentedAttribute):
        msg = f"{model.__name__} has no mapped column {name!r}"
        raise TypeError(msg)
    return column


def ilike_pattern(term: str) -> str:
    """Build a case-insensitive partial-match pattern, escaping ``%``, ``_``, and ``\\``."""

    escaped = (
        term.replace(_ILIKE_ESCAPE, _ILIKE_ESCAPE + _ILIKE_ESCAPE)
        .replace("%", _ILIKE_ESCAPE + "%")
        .replace("_", _ILIKE_ESCAPE + "_")
    )
    return f"%{escaped}%"


def column_ilike(column: InstrumentedAttribute[Any], pattern: str) -> ColumnElement[bool]:
    """ILIKE with an explicit escape so user input is treated as a literal substring."""

    return column.ilike(pattern, escape=_ILIKE_ESCAPE)


def validate_related_search(spec: RelatedSearch, parent: type[Any]) -> None:
    """Ensure every related-search key is a mapped column on the expected model."""

    mapped_column(parent, spec.local_key)
    mapped_column(spec.model, spec.remote_key)
    for field in spec.fields:
        mapped_column(spec.model, field)
    for name, _value in spec.equals:
        mapped_column(spec.model, name)
    for name in spec.null_keys:
        mapped_column(spec.model, name)
    if not spec.fields and not spec.nested:
        msg = f"{spec.model.__name__} related search has no fields or nested matches"
        raise ValueError(msg)
    for child in spec.nested:
        validate_related_search(child, spec.model)


def related_exists(
    spec: RelatedSearch,
    *,
    parent: type[Any],
    tenant_id: UUID,
    pattern: str,
) -> ColumnElement[bool]:
    """EXISTS subquery correlating ``parent.local_key`` to ``spec.model.remote_key``."""

    related = spec.model
    match_parts: list[ColumnElement[bool]] = [
        column_ilike(mapped_column(related, field), pattern) for field in spec.fields
    ]
    match_parts.extend(
        related_exists(child, parent=related, tenant_id=tenant_id, pattern=pattern)
        for child in spec.nested
    )
    criteria: list[ColumnElement[bool]] = [
        mapped_column(related, spec.remote_key) == mapped_column(parent, spec.local_key),
        or_(*match_parts),
    ]
    tenant_col = getattr(related, "tenant_id", None)
    if isinstance(tenant_col, InstrumentedAttribute):
        criteria.append(tenant_col == tenant_id)
    deleted_col = getattr(related, "deleted_at", None)
    if isinstance(deleted_col, InstrumentedAttribute):
        criteria.append(deleted_col.is_(None))
    for name, value in spec.equals:
        criteria.append(mapped_column(related, name) == value)
    for name in spec.null_keys:
        criteria.append(mapped_column(related, name).is_(None))
    return exists(select(literal(1)).select_from(related).where(*criteria))


def search_clause(
    model: type[Any],
    *,
    tenant_id: UUID,
    search: str,
    fields: frozenset[str],
    related: Sequence[RelatedSearch] = (),
) -> ColumnElement[bool]:
    """OR of own-column ILIKE matches and related EXISTS clauses."""

    if not fields and not related:
        msg = "search is not supported by this repository"
        raise ValueError(msg)
    pattern = ilike_pattern(search)
    clauses: list[ColumnElement[bool]] = [
        column_ilike(mapped_column(model, field), pattern) for field in fields
    ]
    clauses.extend(
        related_exists(spec, parent=model, tenant_id=tenant_id, pattern=pattern)
        for spec in related
    )
    return or_(*clauses)


PARTY_FIELDS = frozenset({"name", "code", "trn", "notes"})
PRODUCT_FIELDS = frozenset({"sku", "name", "sales_description", "purchase_description", "hs_code"})
CONTACT_FIELDS = frozenset({"name", "email", "phone"})
WAREHOUSE_FIELDS = frozenset({"code", "name", "phone"})
ADDRESS_FIELDS = frozenset(
    {
        "address_line_1",
        "address_line_2",
        "city",
        "state",
        "country",
        "country_code",
        "postal_code",
    }
)
USER_FIELDS = frozenset({"name", "email", "phone"})
CURRENCY_FIELDS = frozenset({"code", "name", "symbol"})
DOCUMENT_NUMBER_FIELDS = frozenset({"document_number"})


def party_search(local_key: str = "customer_id") -> RelatedSearch:
    from app.crm.customers.models import Customer

    return RelatedSearch(Customer, local_key=local_key, fields=PARTY_FIELDS)


def contact_search(local_key: str = "contact_id") -> RelatedSearch:
    from app.crm.contacts.models import Contact

    return RelatedSearch(Contact, local_key=local_key, fields=CONTACT_FIELDS)


def party_contacts_search() -> RelatedSearch:
    from app.crm.contacts.models import Contact

    return RelatedSearch(
        Contact,
        local_key="id",
        remote_key="customer_id",
        fields=CONTACT_FIELDS,
    )


def extra_address_search() -> RelatedSearch:
    from app.crm.customers.models import CustomerAddress

    return RelatedSearch(
        CustomerAddress,
        local_key="id",
        remote_key="customer_id",
        fields=frozenset({"label"}),
        nested=(address_search("address_id"),),
    )


def address_search(local_key: str) -> RelatedSearch:
    from app.auth.models import Address

    return RelatedSearch(Address, local_key=local_key, fields=ADDRESS_FIELDS)


def product_search(local_key: str = "product_id") -> RelatedSearch:
    from app.inventory_management.products.models import Product

    return RelatedSearch(Product, local_key=local_key, fields=PRODUCT_FIELDS)


def warehouse_search(local_key: str) -> RelatedSearch:
    from app.inventory_management.warehouses.models import Warehouse

    return RelatedSearch(Warehouse, local_key=local_key, fields=WAREHOUSE_FIELDS)


def category_search(local_key: str = "category_id") -> RelatedSearch:
    from app.inventory_management.categories.models import Category

    return RelatedSearch(Category, local_key=local_key, fields=frozenset({"code", "name"}))


def unit_search(local_key: str = "unit_id") -> RelatedSearch:
    from app.inventory_management.units.models import Unit

    return RelatedSearch(Unit, local_key=local_key, fields=frozenset({"code", "name"}))


def currency_search(local_key: str = "currency_id") -> RelatedSearch:
    from app.erp.exchange_rates.models import Currency

    return RelatedSearch(Currency, local_key=local_key, fields=CURRENCY_FIELDS)


def account_search(local_key: str = "account_id") -> RelatedSearch:
    from app.erp.accounting.accounts.models import Account

    return RelatedSearch(Account, local_key=local_key, fields=frozenset({"code", "name"}))


def branch_search(local_key: str = "branch_id") -> RelatedSearch:
    from app.auth.models import Branch

    return RelatedSearch(Branch, local_key=local_key, fields=frozenset({"name", "code", "phone"}))


def user_search(local_key: str) -> RelatedSearch:
    from app.auth.models import User

    return RelatedSearch(User, local_key=local_key, fields=USER_FIELDS)


def employee_search(local_key: str = "salesperson_id") -> RelatedSearch:
    from app.auth.models import Employee

    return RelatedSearch(
        Employee,
        local_key=local_key,
        fields=frozenset({"employee_code", "designation"}),
        nested=(user_search("user_id"),),
    )


def quotation_search(local_key: str = "source_quotation_id") -> RelatedSearch:
    from app.erp.quotation.models import Quotation

    return RelatedSearch(Quotation, local_key=local_key, fields=frozenset({"quote_number"}))


def sales_order_search(local_key: str = "sales_order_id") -> RelatedSearch:
    from app.erp.sales_orders.models import SalesOrder

    return RelatedSearch(
        SalesOrder,
        local_key=local_key,
        fields=frozenset({"document_number", "reference_number", "customer_po_number"}),
    )


def sales_invoice_search(local_key: str = "sales_invoice_id") -> RelatedSearch:
    from app.erp.sales_invoices.models import SalesInvoice

    return RelatedSearch(SalesInvoice, local_key=local_key, fields=DOCUMENT_NUMBER_FIELDS)


def proforma_search(local_key: str = "source_proforma_invoice_id") -> RelatedSearch:
    from app.erp.proforma_invoices.models import ProformaInvoice

    return RelatedSearch(ProformaInvoice, local_key=local_key, fields=DOCUMENT_NUMBER_FIELDS)


def purchase_order_search(local_key: str = "purchase_order_id") -> RelatedSearch:
    from app.erp.purchase_orders.models import PurchaseOrder

    return RelatedSearch(
        PurchaseOrder,
        local_key=local_key,
        fields=frozenset({"document_number", "reference_number"}),
    )


def purchase_invoice_search(local_key: str = "purchase_invoice_id") -> RelatedSearch:
    from app.erp.purchase_invoices.models import PurchaseInvoice

    return RelatedSearch(
        PurchaseInvoice,
        local_key=local_key,
        fields=frozenset({"document_number", "supplier_invoice_number"}),
    )


def goods_receipt_search(local_key: str = "goods_receipt_id") -> RelatedSearch:
    from app.inventory_management.goods_receipts.models import GoodsReceipt

    return RelatedSearch(
        GoodsReceipt,
        local_key=local_key,
        fields=frozenset(
            {
                "document_number",
                "supplier_invoice_number",
                "delivery_challan_number",
                "bill_of_entry_number",
            }
        ),
    )


def delivery_note_search(local_key: str = "delivery_note_id") -> RelatedSearch:
    from app.inventory_management.delivery_notes.models import DeliveryNote

    return RelatedSearch(DeliveryNote, local_key=local_key, fields=DOCUMENT_NUMBER_FIELDS)


def sales_return_search(local_key: str = "sales_return_id") -> RelatedSearch:
    from app.inventory_management.sales_returns.models import SalesReturn

    return RelatedSearch(SalesReturn, local_key=local_key, fields=DOCUMENT_NUMBER_FIELDS)


def purchase_return_search(local_key: str = "purchase_return_id") -> RelatedSearch:
    from app.inventory_management.purchase_returns.models import PurchaseReturn

    return RelatedSearch(PurchaseReturn, local_key=local_key, fields=DOCUMENT_NUMBER_FIELDS)


def shipment_search(local_key: str = "shipment_id") -> RelatedSearch:
    from app.logistics.shipments.models import Shipment

    return RelatedSearch(
        Shipment,
        local_key=local_key,
        fields=frozenset({"document_number", "container_number", "bl_awb_number"}),
    )


def line_search(
    line_model: type[Base],
    parent_fk: str,
    *,
    fields: frozenset[str] = frozenset(),
    product_key: str | None = "product_id",
    nested: tuple[RelatedSearch, ...] = (),
) -> RelatedSearch:
    extra = list(nested)
    if product_key is not None:
        extra.append(product_search(product_key))
    return RelatedSearch(
        line_model,
        local_key="id",
        remote_key=parent_fk,
        fields=fields,
        nested=tuple(extra),
    )


def customer_payment_allocation_search() -> RelatedSearch:
    from app.core.enums import PaymentAllocationSource
    from app.erp.accounting.open_items.models import PaymentAllocation
    from app.erp.credit_notes.models import CreditNote
    from app.erp.proforma_invoices.models import ProformaInvoice

    return RelatedSearch(
        PaymentAllocation,
        local_key="id",
        remote_key="payment_id",
        equals=(("payment_type", PaymentAllocationSource.CUSTOMER_PAYMENT.value),),
        null_keys=("reversed_at",),
        nested=(
            sales_invoice_search("item_id"),
            RelatedSearch(CreditNote, local_key="item_id", fields=DOCUMENT_NUMBER_FIELDS),
            RelatedSearch(ProformaInvoice, local_key="item_id", fields=DOCUMENT_NUMBER_FIELDS),
        ),
    )


def supplier_payment_allocation_search() -> RelatedSearch:
    from app.core.enums import PaymentAllocationSource
    from app.erp.accounting.open_items.models import PaymentAllocation
    from app.erp.debit_notes.models import DebitNote
    from app.erp.purchase_invoices.models import PurchaseInvoice

    return RelatedSearch(
        PaymentAllocation,
        local_key="id",
        remote_key="payment_id",
        equals=(("payment_type", PaymentAllocationSource.SUPPLIER_PAYMENT.value),),
        null_keys=("reversed_at",),
        nested=(
            RelatedSearch(PurchaseInvoice, local_key="item_id", fields=DOCUMENT_NUMBER_FIELDS),
            RelatedSearch(DebitNote, local_key="item_id", fields=DOCUMENT_NUMBER_FIELDS),
        ),
    )

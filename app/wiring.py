"""Application composition: registries that must not live inside common/."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    ACCOUNT_READ,
    ACCOUNT_UPDATE,
    BRANCH_READ,
    BRANCH_UPDATE,
    CONTACT_READ,
    CONTACT_UPDATE,
    CREDIT_NOTE_READ,
    CREDIT_NOTE_UPDATE,
    CUSTOMER_PAYMENT_READ,
    CUSTOMER_PAYMENT_UPDATE,
    CUSTOMER_READ,
    CUSTOMER_UPDATE,
    DEBIT_NOTE_READ,
    DEBIT_NOTE_UPDATE,
    DELIVERY_NOTE_READ,
    DELIVERY_NOTE_UPDATE,
    EMPLOYEE_READ,
    EMPLOYEE_UPDATE,
    GOODS_RECEIPT_READ,
    GOODS_RECEIPT_UPDATE,
    JOURNAL_ENTRY_READ,
    JOURNAL_ENTRY_UPDATE,
    LANDED_COST_READ,
    LANDED_COST_UPDATE,
    PACKAGE_READ,
    PACKAGE_UPDATE,
    PRODUCT_READ,
    PRODUCT_UPDATE,
    PROFORMA_INVOICE_READ,
    PROFORMA_INVOICE_UPDATE,
    PURCHASE_INVOICE_READ,
    PURCHASE_INVOICE_UPDATE,
    PURCHASE_ORDER_READ,
    PURCHASE_ORDER_UPDATE,
    PURCHASE_RETURN_READ,
    PURCHASE_RETURN_UPDATE,
    QUALITY_INSPECTION_READ,
    QUALITY_INSPECTION_UPDATE,
    QUOTATION_READ,
    QUOTATION_UPDATE,
    SALES_INVOICE_READ,
    SALES_INVOICE_UPDATE,
    SALES_ORDER_READ,
    SALES_ORDER_UPDATE,
    SALES_RETURN_READ,
    SALES_RETURN_UPDATE,
    SHIPMENT_READ,
    SHIPMENT_UPDATE,
    STOCK_ADJUSTMENT_READ,
    STOCK_ADJUSTMENT_UPDATE,
    STOCK_TRANSFER_READ,
    STOCK_TRANSFER_UPDATE,
    SUPPLIER_PAYMENT_READ,
    SUPPLIER_PAYMENT_UPDATE,
    SUPPLIER_READ,
    SUPPLIER_UPDATE,
)
from app.common.attachments.entities import AttachmentEntitySpec, EntityRef, Probe, register
from app.common.outbox.models import OutboxEvent
from app.common.registries.delivery_note_dependents import (
    register as register_delivery_note_dependent,
)
from app.common.registries.purchase_invoice_dependents import (
    register as register_purchase_invoice_dependent,
)
from app.common.registries.purchase_return_dependents import (
    register as register_purchase_return_dependent,
)
from app.common.registries.quotation_dependents import register as register_quotation_dependent
from app.common.registries.sales_invoice_dependents import (
    register as register_sales_invoice_dependent,
)
from app.common.registries.unposted_documents import UnpostedDocument
from app.common.registries.unposted_documents import register as register_unposted
from app.common.schemas.pagination import PageParams
from app.core.enums import (
    AttachmentEntityType,
    CompanyType,
    InvoiceDocumentStatus,
    JournalEntryStatus,
    QualityInspectionStatus,
    StockDocumentStatus,
)
from app.core.exceptions import ResourceNotFoundError

logger = logging.getLogger(__name__)

_WIRED = False


def wire_platform() -> None:
    """Idempotently populate cross-cutting registries. Called from create_app()."""

    global _WIRED
    if _WIRED:
        return
    _register_unposted_probes()
    _register_attachment_entities()
    _register_outbox_handlers()
    _register_quotation_dependents()
    _register_delivery_note_dependents()
    _register_sales_invoice_dependents()
    _register_purchase_invoice_dependents()
    _register_purchase_return_dependents()
    _WIRED = True


def _register_unposted_probes() -> None:
    register_unposted("stock_adjustment", _probe_unposted_adjustments)
    register_unposted("stock_transfer", _probe_unposted_transfers)
    register_unposted("goods_receipt", _probe_unposted_goods_receipts)
    register_unposted("quality_inspection", _probe_unposted_quality_inspections)
    register_unposted("delivery_note", _probe_unposted_delivery_notes)
    register_unposted("sales_return", _probe_unposted_sales_returns)
    register_unposted("purchase_return", _probe_unposted_purchase_returns)
    register_unposted("journal_entry", _probe_unposted_journals)
    register_unposted("sales_invoice", _probe_unposted_sales_invoices)
    register_unposted("purchase_invoice", _probe_unposted_purchase_invoices)
    register_unposted("credit_note", _probe_unposted_credit_notes)
    register_unposted("debit_note", _probe_unposted_debit_notes)
    register_unposted("customer_payment", _probe_unposted_customer_payments)
    register_unposted("supplier_payment", _probe_unposted_supplier_payments)
    register_unposted("landed_cost", _probe_unposted_landed_costs)


async def _probe_unposted_adjustments(
    session: AsyncSession,
    tenant_id: UUID,
    as_of: date,
    page: PageParams,
) -> tuple[list[UnpostedDocument], int]:
    from app.inventory_management.stock_adjustments.service import StockAdjustmentService

    rows, total = await StockAdjustmentService(session).list(
        tenant_id,
        page=page,
        status=StockDocumentStatus.DRAFT.value,
        document_date_to=as_of,
    )
    documents = [
        UnpostedDocument(
            id=row.id,
            document_type="stock_adjustment",
            document_number=row.document_number,
            document_date=row.document_date,
            status=str(row.status),
        )
        for row in rows
    ]
    return documents, total


async def _probe_unposted_transfers(
    session: AsyncSession,
    tenant_id: UUID,
    as_of: date,
    page: PageParams,
) -> tuple[list[UnpostedDocument], int]:
    from app.inventory_management.stock_transfers.service import StockTransferService

    rows, total = await StockTransferService(session).list(
        tenant_id,
        page=page,
        status=StockDocumentStatus.DRAFT.value,
        document_date_to=as_of,
    )
    documents = [
        UnpostedDocument(
            id=row.id,
            document_type="stock_transfer",
            document_number=row.document_number,
            document_date=row.document_date,
            status=str(row.status),
        )
        for row in rows
    ]
    return documents, total


async def _probe_unposted_goods_receipts(
    session: AsyncSession,
    tenant_id: UUID,
    as_of: date,
    page: PageParams,
) -> tuple[list[UnpostedDocument], int]:
    from app.inventory_management.goods_receipts.service import GoodsReceiptService

    rows, total = await GoodsReceiptService(session).list(
        tenant_id,
        page=page,
        status=StockDocumentStatus.DRAFT.value,
        document_date_to=as_of,
    )
    documents = [
        UnpostedDocument(
            id=row.id,
            document_type="goods_receipt",
            document_number=row.document_number,
            document_date=row.document_date,
            status=str(row.status),
        )
        for row in rows
    ]
    return documents, total


async def _probe_unposted_quality_inspections(
    session: AsyncSession,
    tenant_id: UUID,
    as_of: date,
    page: PageParams,
) -> tuple[list[UnpostedDocument], int]:
    from app.inventory_management.quality_inspections.service import QualityInspectionService

    rows, total = await QualityInspectionService(session).list(
        tenant_id,
        page=page,
        status=QualityInspectionStatus.DRAFT.value,
        inspection_date_to=as_of,
    )
    documents = [
        UnpostedDocument(
            id=row.id,
            document_type="quality_inspection",
            document_number=row.document_number,
            document_date=row.inspection_date,
            status=str(row.status),
        )
        for row in rows
    ]
    return documents, total


async def _probe_unposted_delivery_notes(
    session: AsyncSession,
    tenant_id: UUID,
    as_of: date,
    page: PageParams,
) -> tuple[list[UnpostedDocument], int]:
    from app.inventory_management.delivery_notes.service import DeliveryNoteService

    rows, total = await DeliveryNoteService(session).list(
        tenant_id,
        page=page,
        status=StockDocumentStatus.DRAFT.value,
        document_date_to=as_of,
    )
    documents = [
        UnpostedDocument(
            id=row.id,
            document_type="delivery_note",
            document_number=row.document_number,
            document_date=row.document_date,
            status=str(row.status),
        )
        for row in rows
    ]
    return documents, total


async def _probe_unposted_sales_returns(
    session: AsyncSession,
    tenant_id: UUID,
    as_of: date,
    page: PageParams,
) -> tuple[list[UnpostedDocument], int]:
    from app.inventory_management.sales_returns.service import SalesReturnService

    rows, total = await SalesReturnService(session).list(
        tenant_id,
        page=page,
        status=StockDocumentStatus.DRAFT.value,
        document_date_to=as_of,
    )
    documents = [
        UnpostedDocument(
            id=row.id,
            document_type="sales_return",
            document_number=row.document_number,
            document_date=row.document_date,
            status=str(row.status),
        )
        for row in rows
    ]
    return documents, total


async def _probe_unposted_purchase_returns(
    session: AsyncSession,
    tenant_id: UUID,
    as_of: date,
    page: PageParams,
) -> tuple[list[UnpostedDocument], int]:
    from app.inventory_management.purchase_returns.service import PurchaseReturnService

    rows, total = await PurchaseReturnService(session).list(
        tenant_id,
        page=page,
        status=StockDocumentStatus.DRAFT.value,
        document_date_to=as_of,
    )
    documents = [
        UnpostedDocument(
            id=row.id,
            document_type="purchase_return",
            document_number=row.document_number,
            document_date=row.document_date,
            status=str(row.status),
        )
        for row in rows
    ]
    return documents, total


async def _probe_unposted_journals(
    session: AsyncSession,
    tenant_id: UUID,
    as_of: date,
    page: PageParams,
) -> tuple[list[UnpostedDocument], int]:
    from app.erp.accounting.ledger.service import JournalEntryService

    rows, total = await JournalEntryService(session).list(
        tenant_id,
        page=page,
        status=JournalEntryStatus.DRAFT.value,
        entry_date_to=as_of,
    )
    documents = [
        UnpostedDocument(
            id=row.id,
            document_type="journal_entry",
            document_number=row.document_number,
            document_date=row.entry_date,
            status=str(row.status),
        )
        for row in rows
    ]
    return documents, total


async def _probe_unposted_sales_invoices(
    session: AsyncSession,
    tenant_id: UUID,
    as_of: date,
    page: PageParams,
) -> tuple[list[UnpostedDocument], int]:
    from app.erp.sales_invoices.service import SalesInvoiceService

    rows, total = await SalesInvoiceService(session).list(
        tenant_id,
        page=page,
        status=InvoiceDocumentStatus.DRAFT.value,
        invoice_date_to=as_of,
    )
    documents = [
        UnpostedDocument(
            id=row.id,
            document_type="sales_invoice",
            document_number=row.document_number,
            document_date=row.invoice_date,
            status=str(row.status),
        )
        for row in rows
    ]
    return documents, total


async def _probe_unposted_purchase_invoices(
    session: AsyncSession,
    tenant_id: UUID,
    as_of: date,
    page: PageParams,
) -> tuple[list[UnpostedDocument], int]:
    from app.erp.purchase_invoices.service import PurchaseInvoiceService

    rows, total = await PurchaseInvoiceService(session).list(
        tenant_id,
        page=page,
        status=InvoiceDocumentStatus.DRAFT.value,
        invoice_date_to=as_of,
    )
    documents = [
        UnpostedDocument(
            id=row.id,
            document_type="purchase_invoice",
            document_number=row.document_number,
            document_date=row.invoice_date,
            status=str(row.status),
        )
        for row in rows
    ]
    return documents, total


async def _probe_unposted_credit_notes(
    session: AsyncSession,
    tenant_id: UUID,
    as_of: date,
    page: PageParams,
) -> tuple[list[UnpostedDocument], int]:
    from app.erp.credit_notes.service import CreditNoteService

    rows, total = await CreditNoteService(session).list(
        tenant_id,
        page=page,
        status=InvoiceDocumentStatus.DRAFT.value,
        credit_note_date_to=as_of,
    )
    documents = [
        UnpostedDocument(
            id=row.id,
            document_type="credit_note",
            document_number=row.document_number,
            document_date=row.credit_note_date,
            status=str(row.status),
        )
        for row in rows
    ]
    return documents, total


async def _probe_unposted_debit_notes(
    session: AsyncSession,
    tenant_id: UUID,
    as_of: date,
    page: PageParams,
) -> tuple[list[UnpostedDocument], int]:
    from app.erp.debit_notes.service import DebitNoteService

    rows, total = await DebitNoteService(session).list(
        tenant_id,
        page=page,
        status=InvoiceDocumentStatus.DRAFT.value,
        debit_note_date_to=as_of,
    )
    documents = [
        UnpostedDocument(
            id=row.id,
            document_type="debit_note",
            document_number=row.document_number,
            document_date=row.debit_note_date,
            status=str(row.status),
        )
        for row in rows
    ]
    return documents, total


async def _probe_unposted_customer_payments(
    session: AsyncSession,
    tenant_id: UUID,
    as_of: date,
    page: PageParams,
) -> tuple[list[UnpostedDocument], int]:
    from app.erp.accounting.customer_payments.service import CustomerPaymentService

    rows, total = await CustomerPaymentService(session).list(
        tenant_id,
        page=page,
        status=InvoiceDocumentStatus.DRAFT.value,
        payment_date_to=as_of,
    )
    documents = [
        UnpostedDocument(
            id=row.id,
            document_type="customer_payment",
            document_number=row.document_number,
            document_date=row.payment_date,
            status=str(row.status),
        )
        for row in rows
    ]
    return documents, total


async def _probe_unposted_supplier_payments(
    session: AsyncSession,
    tenant_id: UUID,
    as_of: date,
    page: PageParams,
) -> tuple[list[UnpostedDocument], int]:
    from app.erp.accounting.supplier_payments.service import SupplierPaymentService

    rows, total = await SupplierPaymentService(session).list(
        tenant_id,
        page=page,
        status=InvoiceDocumentStatus.DRAFT.value,
        payment_date_to=as_of,
    )
    documents = [
        UnpostedDocument(
            id=row.id,
            document_type="supplier_payment",
            document_number=row.document_number,
            document_date=row.payment_date,
            status=str(row.status),
        )
        for row in rows
    ]
    return documents, total


async def _probe_unposted_landed_costs(
    session: AsyncSession,
    tenant_id: UUID,
    as_of: date,
    page: PageParams,
) -> tuple[list[UnpostedDocument], int]:
    from app.erp.landed_costs.service import LandedCostService

    rows, total = await LandedCostService(session).list(
        tenant_id,
        page=page,
        status=StockDocumentStatus.DRAFT.value,
        document_date_to=as_of,
    )
    documents = [
        UnpostedDocument(
            id=row.id,
            document_type="landed_cost",
            document_number=row.document_number,
            document_date=row.document_date,
            status=str(row.status),
        )
        for row in rows
    ]
    return documents, total


def _register_attachment_entities() -> None:
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.CUSTOMER,
            CUSTOMER_READ,
            CUSTOMER_UPDATE,
            _probe_customer,
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.SUPPLIER,
            SUPPLIER_READ,
            SUPPLIER_UPDATE,
            _probe_supplier,
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.CONTACT,
            CONTACT_READ,
            CONTACT_UPDATE,
            _probe_via_get(_contact_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.PRODUCT,
            PRODUCT_READ,
            PRODUCT_UPDATE,
            _probe_via_get(_product_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.QUOTATION,
            QUOTATION_READ,
            QUOTATION_UPDATE,
            _probe_via_get(_quotation_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.SALES_ORDER,
            SALES_ORDER_READ,
            SALES_ORDER_UPDATE,
            _probe_via_get(_sales_order_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.PURCHASE_ORDER,
            PURCHASE_ORDER_READ,
            PURCHASE_ORDER_UPDATE,
            _probe_via_get(_purchase_order_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.BRANCH,
            BRANCH_READ,
            BRANCH_UPDATE,
            _probe_via_get(_branch_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.EMPLOYEE,
            EMPLOYEE_READ,
            EMPLOYEE_UPDATE,
            _probe_employee,
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.STOCK_TRANSFER,
            STOCK_TRANSFER_READ,
            STOCK_TRANSFER_UPDATE,
            _probe_via_get(_stock_transfer_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.STOCK_ADJUSTMENT,
            STOCK_ADJUSTMENT_READ,
            STOCK_ADJUSTMENT_UPDATE,
            _probe_via_get(_stock_adjustment_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.PROFORMA_INVOICE,
            PROFORMA_INVOICE_READ,
            PROFORMA_INVOICE_UPDATE,
            _probe_via_get(_proforma_invoice_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.GOODS_RECEIPT,
            GOODS_RECEIPT_READ,
            GOODS_RECEIPT_UPDATE,
            _probe_via_get(_goods_receipt_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.QUALITY_INSPECTION,
            QUALITY_INSPECTION_READ,
            QUALITY_INSPECTION_UPDATE,
            _probe_via_get(_quality_inspection_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.DELIVERY_NOTE,
            DELIVERY_NOTE_READ,
            DELIVERY_NOTE_UPDATE,
            _probe_via_get(_delivery_note_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.PACKAGE,
            PACKAGE_READ,
            PACKAGE_UPDATE,
            _probe_via_get(_package_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.SHIPMENT,
            SHIPMENT_READ,
            SHIPMENT_UPDATE,
            _probe_via_get(_shipment_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.SALES_RETURN,
            SALES_RETURN_READ,
            SALES_RETURN_UPDATE,
            _probe_via_get(_sales_return_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.PURCHASE_RETURN,
            PURCHASE_RETURN_READ,
            PURCHASE_RETURN_UPDATE,
            _probe_via_get(_purchase_return_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.JOURNAL_ENTRY,
            JOURNAL_ENTRY_READ,
            JOURNAL_ENTRY_UPDATE,
            _probe_via_get(_journal_entry_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.ACCOUNT,
            ACCOUNT_READ,
            ACCOUNT_UPDATE,
            _probe_via_get(_account_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.SALES_INVOICE,
            SALES_INVOICE_READ,
            SALES_INVOICE_UPDATE,
            _probe_via_get(_sales_invoice_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.PURCHASE_INVOICE,
            PURCHASE_INVOICE_READ,
            PURCHASE_INVOICE_UPDATE,
            _probe_via_get(_purchase_invoice_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.CREDIT_NOTE,
            CREDIT_NOTE_READ,
            CREDIT_NOTE_UPDATE,
            _probe_via_get(_credit_note_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.DEBIT_NOTE,
            DEBIT_NOTE_READ,
            DEBIT_NOTE_UPDATE,
            _probe_via_get(_debit_note_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.CUSTOMER_PAYMENT,
            CUSTOMER_PAYMENT_READ,
            CUSTOMER_PAYMENT_UPDATE,
            _probe_via_get(_customer_payment_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.SUPPLIER_PAYMENT,
            SUPPLIER_PAYMENT_READ,
            SUPPLIER_PAYMENT_UPDATE,
            _probe_via_get(_supplier_payment_get),
        )
    )
    register(
        AttachmentEntitySpec(
            AttachmentEntityType.LANDED_COST,
            LANDED_COST_READ,
            LANDED_COST_UPDATE,
            _probe_via_get(_landed_cost_get),
        )
    )


def _probe_via_get(
    getter: Callable[[AsyncSession, UUID, UUID], Awaitable[object]],
) -> Probe:
    async def probe(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> EntityRef:
        try:
            row = await getter(session, tenant_id, entity_id)
        except ResourceNotFoundError:
            return EntityRef(exists=False)
        return EntityRef(exists=True, is_posted=bool(getattr(row, "is_posted", False)))

    return probe


async def _probe_customer(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> EntityRef:
    from app.crm.customers.service import CUSTOMER_PARTY_ROLE, CustomerService

    service = CustomerService(session, role=CUSTOMER_PARTY_ROLE)
    try:
        row = await service.require_party(tenant_id, entity_id)
    except ResourceNotFoundError:
        return EntityRef(exists=False)
    if CompanyType(row.company_type) not in CUSTOMER_PARTY_ROLE.visible_types:
        return EntityRef(exists=False)
    return EntityRef(exists=True)


async def _probe_supplier(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> EntityRef:
    from app.crm.customers.service import SUPPLIER_PARTY_ROLE, CustomerService

    service = CustomerService(session, role=SUPPLIER_PARTY_ROLE)
    try:
        row = await service.require_party(tenant_id, entity_id)
    except ResourceNotFoundError:
        return EntityRef(exists=False)
    if CompanyType(row.company_type) not in SUPPLIER_PARTY_ROLE.visible_types:
        return EntityRef(exists=False)
    return EntityRef(exists=True)


async def _probe_employee(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> EntityRef:
    from app.auth.org_service import OrganizationService

    exists = await OrganizationService(session).employee_exists(tenant_id, entity_id)
    return EntityRef(exists=exists)


async def _contact_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.crm.contacts.service import ContactService

    return await ContactService(session).get(tenant_id, entity_id)


async def _product_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.inventory_management.products.service import ProductService

    return await ProductService(session).get(tenant_id, entity_id)


async def _quotation_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.erp.quotation.service import QuotationService

    return await QuotationService(session).get(tenant_id, entity_id)


async def _sales_order_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.erp.sales_orders.service import SalesOrderService

    return await SalesOrderService(session).get(tenant_id, entity_id)


async def _purchase_order_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.erp.purchase_orders.service import PurchaseOrderService

    return await PurchaseOrderService(session).get(tenant_id, entity_id)


async def _branch_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.auth.org_service import OrganizationService

    return await OrganizationService(session).get_branch(tenant_id, entity_id)


async def _stock_transfer_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.inventory_management.stock_transfers.service import StockTransferService

    return await StockTransferService(session).get(tenant_id, entity_id)


async def _stock_adjustment_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.inventory_management.stock_adjustments.service import StockAdjustmentService

    return await StockAdjustmentService(session).get(tenant_id, entity_id)


async def _proforma_invoice_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.erp.proforma_invoices.service import ProformaInvoiceService

    return await ProformaInvoiceService(session).get(tenant_id, entity_id)


async def _goods_receipt_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.inventory_management.goods_receipts.service import GoodsReceiptService

    return await GoodsReceiptService(session).get(tenant_id, entity_id)


async def _quality_inspection_get(
    session: AsyncSession, tenant_id: UUID, entity_id: UUID
) -> object:
    from app.inventory_management.quality_inspections.service import QualityInspectionService

    return await QualityInspectionService(session).get(tenant_id, entity_id)


async def _delivery_note_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.inventory_management.delivery_notes.service import DeliveryNoteService

    return await DeliveryNoteService(session).get(tenant_id, entity_id)


async def _package_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.inventory_management.packages.service import PackageService

    return await PackageService(session).get(tenant_id, entity_id)


async def _shipment_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.logistics.shipments.service import ShipmentService

    return await ShipmentService(session).get(tenant_id, entity_id)


async def _sales_return_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.inventory_management.sales_returns.service import SalesReturnService

    return await SalesReturnService(session).get(tenant_id, entity_id)


async def _purchase_return_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.inventory_management.purchase_returns.service import PurchaseReturnService

    return await PurchaseReturnService(session).get(tenant_id, entity_id)


async def _journal_entry_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.erp.accounting.ledger.service import JournalEntryService

    return await JournalEntryService(session).get(tenant_id, entity_id)


async def _account_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.erp.accounting.accounts.service import AccountService

    return await AccountService(session).get(tenant_id, entity_id)


async def _sales_invoice_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.erp.sales_invoices.service import SalesInvoiceService

    return await SalesInvoiceService(session).get(tenant_id, entity_id)


async def _purchase_invoice_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.erp.purchase_invoices.service import PurchaseInvoiceService

    return await PurchaseInvoiceService(session).get(tenant_id, entity_id)


async def _credit_note_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.erp.credit_notes.service import CreditNoteService

    return await CreditNoteService(session).get(tenant_id, entity_id)


async def _debit_note_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.erp.debit_notes.service import DebitNoteService

    return await DebitNoteService(session).get(tenant_id, entity_id)


async def _customer_payment_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.erp.accounting.customer_payments.service import CustomerPaymentService

    return await CustomerPaymentService(session).get(tenant_id, entity_id)


async def _supplier_payment_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.erp.accounting.supplier_payments.service import SupplierPaymentService

    return await SupplierPaymentService(session).get(tenant_id, entity_id)


async def _landed_cost_get(session: AsyncSession, tenant_id: UUID, entity_id: UUID) -> object:
    from app.erp.landed_costs.service import LandedCostService

    return await LandedCostService(session).get(tenant_id, entity_id)


def _register_outbox_handlers() -> None:
    # Phases 34 and 35 replace these logging no-ops with real handlers.
    from app.common.outbox.handlers import register as register_outbox

    for event_type in (
        "sales.quotation.revised",
        "sales.proforma_invoice.sent",
        "sales.proforma_invoice.confirmed",
        "sales.sales_order.acknowledged",
        "purchase.goods_receipt.posted",
        "purchase.goods_receipt.cancelled",
        "purchase.quality_inspection.approved",
        "inventory.stock_transfer.posted",
        "inventory.stock_transfer.cancelled",
        "sales.delivery_note.posted",
        "sales.delivery_note.cancelled",
        "sales.sales_return.posted",
        "sales.sales_return.cancelled",
        "purchase.purchase_return.posted",
        "purchase.purchase_return.cancelled",
        "accounting.journal_entry.posted",
        "accounting.journal_entry.reversed",
        "sales.sales_invoice.posted",
        "sales.sales_invoice.cancelled",
        "erp.einvoice.submit_requested",
        "purchase.purchase_invoice.posted",
        "purchase.purchase_invoice.cancelled",
        "sales.credit_note.posted",
        "sales.credit_note.cancelled",
        "purchase.debit_note.posted",
        "purchase.debit_note.cancelled",
        "sales.customer_payment.posted",
        "sales.customer_payment.cancelled",
        "sales.customer_payment.allocated",
        "purchase.supplier_payment.posted",
        "purchase.supplier_payment.cancelled",
        "purchase.supplier_payment.allocated",
        "purchase.landed_cost.posted",
        "purchase.landed_cost.cancelled",
    ):
        register_outbox(event_type, _log_outbox_event)


async def _log_outbox_event(event: OutboxEvent) -> None:
    logger.info(
        "outbox event acknowledged (no-op until phases 34/35)",
        extra={
            "event_type": event.event_type,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": str(event.aggregate_id),
        },
    )


def _register_quotation_dependents() -> None:
    register_quotation_dependent("proforma_invoice", _probe_live_proforma_for_quotation)


async def _probe_live_proforma_for_quotation(
    session: AsyncSession, tenant_id: UUID, quotation_id: UUID
) -> bool:
    from app.erp.proforma_invoices.service import ProformaInvoiceService

    return await ProformaInvoiceService(session).has_live_for_quotation(tenant_id, quotation_id)


def _register_delivery_note_dependents() -> None:
    register_delivery_note_dependent("shipment", _probe_shipment_for_delivery_note)
    register_delivery_note_dependent("sales_return", _probe_sales_return_for_delivery_note)
    register_delivery_note_dependent("sales_invoice", _probe_sales_invoice_for_delivery_note)


async def _probe_shipment_for_delivery_note(
    session: AsyncSession, tenant_id: UUID, delivery_note_id: UUID
) -> bool:
    from app.logistics.shipments.service import ShipmentService

    return await ShipmentService(session).delivery_note_is_shipped(tenant_id, delivery_note_id)


async def _probe_sales_return_for_delivery_note(
    session: AsyncSession, tenant_id: UUID, delivery_note_id: UUID
) -> bool:
    from app.inventory_management.sales_returns.service import SalesReturnService

    return await SalesReturnService(session).has_live_for_delivery_note(tenant_id, delivery_note_id)


async def _probe_sales_invoice_for_delivery_note(
    session: AsyncSession, tenant_id: UUID, delivery_note_id: UUID
) -> bool:
    from app.erp.sales_invoices.service import SalesInvoiceService

    return await SalesInvoiceService(session).has_live_for_delivery_note(tenant_id, delivery_note_id)


def _register_sales_invoice_dependents() -> None:
    register_sales_invoice_dependent("credit_note", _probe_credit_note_for_sales_invoice)
    register_sales_invoice_dependent("customer_payment", _probe_customer_payment_for_sales_invoice)


async def _probe_credit_note_for_sales_invoice(
    session: AsyncSession, tenant_id: UUID, sales_invoice_id: UUID
) -> bool:
    from app.erp.credit_notes.service import CreditNoteService

    return await CreditNoteService(session).has_live_for_sales_invoice(tenant_id, sales_invoice_id)


async def _probe_customer_payment_for_sales_invoice(
    session: AsyncSession, tenant_id: UUID, sales_invoice_id: UUID
) -> bool:
    from app.erp.accounting.customer_payments.service import CustomerPaymentService

    return await CustomerPaymentService(session).has_live_for_sales_invoice(
        tenant_id, sales_invoice_id
    )


def _register_purchase_invoice_dependents() -> None:
    register_purchase_invoice_dependent("debit_note", _probe_debit_note_for_purchase_invoice)
    register_purchase_invoice_dependent(
        "supplier_payment", _probe_supplier_payment_for_purchase_invoice
    )


async def _probe_debit_note_for_purchase_invoice(
    session: AsyncSession, tenant_id: UUID, purchase_invoice_id: UUID
) -> bool:
    from app.erp.debit_notes.service import DebitNoteService

    return await DebitNoteService(session).has_live_for_purchase_invoice(
        tenant_id, purchase_invoice_id
    )


async def _probe_supplier_payment_for_purchase_invoice(
    session: AsyncSession, tenant_id: UUID, purchase_invoice_id: UUID
) -> bool:
    from app.erp.accounting.supplier_payments.service import SupplierPaymentService

    return await SupplierPaymentService(session).has_live_for_purchase_invoice(
        tenant_id, purchase_invoice_id
    )


def _register_purchase_return_dependents() -> None:
    register_purchase_return_dependent("debit_note", _probe_debit_note_for_purchase_return)


async def _probe_debit_note_for_purchase_return(
    session: AsyncSession, tenant_id: UUID, purchase_return_id: UUID
) -> bool:
    from app.erp.debit_notes.service import DebitNoteService

    return await DebitNoteService(session).has_live_for_purchase_return(
        tenant_id, purchase_return_id
    )

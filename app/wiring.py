"""Application composition: registries that must not live inside common/."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

import logging

from app.auth.catalog import (
    BRANCH_READ,
    BRANCH_UPDATE,
    CONTACT_READ,
    CONTACT_UPDATE,
    CUSTOMER_READ,
    CUSTOMER_UPDATE,
    EMPLOYEE_READ,
    EMPLOYEE_UPDATE,
    PRODUCT_READ,
    PRODUCT_UPDATE,
    PROFORMA_INVOICE_READ,
    PROFORMA_INVOICE_UPDATE,
    PURCHASE_ORDER_READ,
    PURCHASE_ORDER_UPDATE,
    QUOTATION_READ,
    QUOTATION_UPDATE,
    SALES_ORDER_READ,
    SALES_ORDER_UPDATE,
    STOCK_ADJUSTMENT_READ,
    STOCK_ADJUSTMENT_UPDATE,
    STOCK_TRANSFER_READ,
    STOCK_TRANSFER_UPDATE,
    SUPPLIER_READ,
    SUPPLIER_UPDATE,
)
from app.common.attachments.entities import AttachmentEntitySpec, EntityRef, Probe, register
from app.common.outbox.models import OutboxEvent
from app.common.registries.quotation_dependents import register as register_quotation_dependent
from app.common.registries.unposted_documents import UnpostedDocument
from app.common.registries.unposted_documents import register as register_unposted
from app.common.schemas.pagination import PageParams
from app.core.enums import AttachmentEntityType, CompanyType, StockDocumentStatus
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
    _WIRED = True


def _register_unposted_probes() -> None:
    register_unposted("stock_adjustment", _probe_unposted_adjustments)
    register_unposted("stock_transfer", _probe_unposted_transfers)


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


def _register_outbox_handlers() -> None:
    # Phases 34 and 35 replace these logging no-ops with real handlers.
    from app.common.outbox.handlers import register as register_outbox

    for event_type in (
        "erp.quotation.revised",
        "erp.proforma_invoice.sent",
        "erp.proforma_invoice.confirmed",
        "erp.sales_order.acknowledged",
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

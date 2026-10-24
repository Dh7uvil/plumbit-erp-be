"""Validate and resolve operational document links for vouchers and cost sheets."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError

# Types exposed in the legacy cost sheet / voucher document picker (frontend document-links.ts).
SOURCE_DOCUMENT_TYPES = frozenset(
    {
        "QUOTATION",
        "PROFORMA_INVOICE",
        "SALES_ORDER",
        "DELIVERY_NOTE",
        "SALES_INVOICE",
        "CREDIT_NOTE",
        "PURCHASE_ORDER",
        "GOODS_RECEIPT",
        "PURCHASE_INVOICE",
        "DEBIT_NOTE",
        "QUALITY_INSPECTION",
        "PACKAGE",
        "SHIPMENT",
        "SALES_RETURN",
        "PURCHASE_RETURN",
        "CUSTOMER_PAYMENT",
        "SUPPLIER_PAYMENT",
    }
)

_MODEL_BY_TYPE: dict[str, tuple[str, str]] = {
    "QUOTATION": ("app.erp.quotations.models", "Quotation"),
    "PROFORMA_INVOICE": ("app.erp.proforma_invoices.models", "ProformaInvoice"),
    "SALES_ORDER": ("app.erp.sales_orders.models", "SalesOrder"),
    "DELIVERY_NOTE": ("app.inventory_management.delivery_notes.models", "DeliveryNote"),
    "SALES_INVOICE": ("app.erp.sales_invoices.models", "SalesInvoice"),
    "CREDIT_NOTE": ("app.erp.credit_notes.models", "CreditNote"),
    "PURCHASE_ORDER": ("app.erp.purchase_orders.models", "PurchaseOrder"),
    "GOODS_RECEIPT": ("app.inventory_management.goods_receipts.models", "GoodsReceipt"),
    "PURCHASE_INVOICE": ("app.erp.purchase_invoices.models", "PurchaseInvoice"),
    "DEBIT_NOTE": ("app.erp.debit_notes.models", "DebitNote"),
    "QUALITY_INSPECTION": (
        "app.inventory_management.quality_inspections.models",
        "QualityInspection",
    ),
    "PACKAGE": ("app.inventory_management.packages.models", "Package"),
    "SHIPMENT": ("app.inventory_management.shipments.models", "Shipment"),
    "SALES_RETURN": ("app.inventory_management.sales_returns.models", "SalesReturn"),
    "PURCHASE_RETURN": ("app.inventory_management.purchase_returns.models", "PurchaseReturn"),
    "CUSTOMER_PAYMENT": ("app.erp.accounting.customer_payments.models", "CustomerPayment"),
    "SUPPLIER_PAYMENT": ("app.erp.accounting.supplier_payments.models", "SupplierPayment"),
}


def _import_model(document_type: str):
    module_path, class_name = _MODEL_BY_TYPE[document_type]
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, class_name)


async def require_source_document(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    document_type: str,
    document_id: UUID,
) -> str:
    """Return document_number for a validated source document."""
    normalized = document_type.strip().upper().replace("-", "_").replace(" ", "_")
    if normalized not in SOURCE_DOCUMENT_TYPES:
        raise ValidationError(f"Unsupported document type: {document_type}")
    model = _import_model(normalized)
    statement = select(model).where(
        model.tenant_id == tenant_id,
        model.id == document_id,
        model.deleted_at.is_(None),
    )
    row = (await session.execute(statement)).scalar_one_or_none()
    if row is None:
        raise ValidationError("Selected document was not found")
    number = getattr(row, "document_number", None)
    if not number:
        raise ValidationError("Selected document has no document number")
    return str(number)


def legacy_fk_columns(document_type: str, document_id: UUID) -> dict[str, UUID]:
    """Map source document to legacy cost sheet FK columns when applicable."""
    mapping: dict[str, str] = {
        "PURCHASE_INVOICE": "purchase_invoice_id",
        "PURCHASE_ORDER": "purchase_order_id",
        "SHIPMENT": "shipment_id",
        "PROFORMA_INVOICE": "proforma_invoice_id",
    }
    column = mapping.get(document_type)
    if column is None:
        return {}
    return {column: document_id}

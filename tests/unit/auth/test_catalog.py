"""Unit tests for the identity permission catalog."""

from app.auth.catalog import CATALOG_PERMISSIONS, IDENTITY_PERMISSIONS, SYSTEM_ADMIN_ROLE_NAME


def test_system_role_is_superadmin() -> None:
    assert SYSTEM_ADMIN_ROLE_NAME == "Superadmin"


def test_catalog_includes_organization_and_audit_permissions() -> None:
    assert "identity.user.read" in IDENTITY_PERMISSIONS
    assert "identity.organization.read" in IDENTITY_PERMISSIONS
    assert "identity.organization.update" in IDENTITY_PERMISSIONS
    assert "identity.branch.create" in IDENTITY_PERMISSIONS
    assert "identity.department.delete" in IDENTITY_PERMISSIONS
    assert "identity.employee.update" in IDENTITY_PERMISSIONS
    assert "identity.audit_log.read" in IDENTITY_PERMISSIONS
    assert "identity.permission.read" in IDENTITY_PERMISSIONS
    assert "identity.attachment.create" in IDENTITY_PERMISSIONS
    assert "identity.attachment.read" in IDENTITY_PERMISSIONS
    assert "identity.attachment.update" in IDENTITY_PERMISSIONS
    assert "identity.attachment.delete" in IDENTITY_PERMISSIONS
    assert "identity.outbox_event.read" in IDENTITY_PERMISSIONS
    assert "identity.outbox_event.retry" in IDENTITY_PERMISSIONS


def test_catalog_includes_quote_ready_permissions() -> None:
    assert "crm.customer.create" in CATALOG_PERMISSIONS
    assert "erp.supplier.create" in CATALOG_PERMISSIONS
    assert "erp.supplier.read" in CATALOG_PERMISSIONS
    assert "erp.supplier.update" in CATALOG_PERMISSIONS
    assert "erp.supplier.delete" in CATALOG_PERMISSIONS
    assert "erp.supplier_product.create" in CATALOG_PERMISSIONS
    assert "erp.supplier_product.read" in CATALOG_PERMISSIONS
    assert "erp.supplier_product.update" in CATALOG_PERMISSIONS
    assert "erp.supplier_product.delete" in CATALOG_PERMISSIONS
    assert "erp.supplier_product.link" in CATALOG_PERMISSIONS
    assert "crm.contact.read" in CATALOG_PERMISSIONS
    assert "inventory.product.create" in CATALOG_PERMISSIONS
    assert "inventory.price_list.update" in CATALOG_PERMISSIONS
    assert "inventory.warehouse.create" in CATALOG_PERMISSIONS
    assert "erp.currency.read" in CATALOG_PERMISSIONS
    assert "erp.exchange_rate.create" in CATALOG_PERMISSIONS
    assert "erp.tax.read" in CATALOG_PERMISSIONS
    assert "erp.quotation.approve" in CATALOG_PERMISSIONS
    assert "erp.quotation.send" in CATALOG_PERMISSIONS
    assert "erp.quotation.revise" in CATALOG_PERMISSIONS
    assert "erp.sales_order.acknowledge" in CATALOG_PERMISSIONS
    assert "erp.proforma_invoice.create" in CATALOG_PERMISSIONS
    assert "erp.proforma_invoice.read" in CATALOG_PERMISSIONS
    assert "erp.proforma_invoice.update" in CATALOG_PERMISSIONS
    assert "erp.proforma_invoice.delete" in CATALOG_PERMISSIONS
    assert "erp.proforma_invoice.send" in CATALOG_PERMISSIONS
    assert "erp.proforma_invoice.confirm" in CATALOG_PERMISSIONS
    assert "erp.period.lock" in CATALOG_PERMISSIONS
    assert "erp.period.override" in CATALOG_PERMISSIONS
    assert "erp.account.create" in CATALOG_PERMISSIONS
    assert "erp.account.read" in CATALOG_PERMISSIONS
    assert "erp.journal_entry.post" in CATALOG_PERMISSIONS
    assert "erp.journal_entry.reverse" in CATALOG_PERMISSIONS
    assert "erp.opening_balance.manage" in CATALOG_PERMISSIONS
    assert "erp.report.ledger" in CATALOG_PERMISSIONS
    assert "erp.document_sequence.create" in CATALOG_PERMISSIONS
    assert "inventory.stock.read" in CATALOG_PERMISSIONS
    assert "inventory.stock.update" in CATALOG_PERMISSIONS
    assert "inventory.stock_transfer.create" in CATALOG_PERMISSIONS
    assert "inventory.stock_transfer.post" in CATALOG_PERMISSIONS
    assert "inventory.stock_adjustment.create" in CATALOG_PERMISSIONS
    assert "inventory.stock_adjustment.post" in CATALOG_PERMISSIONS
    assert "inventory.cost.read" in CATALOG_PERMISSIONS
    assert "inventory.goods_receipt.create" in CATALOG_PERMISSIONS
    assert "inventory.goods_receipt.read" in CATALOG_PERMISSIONS
    assert "inventory.goods_receipt.update" in CATALOG_PERMISSIONS
    assert "inventory.goods_receipt.delete" in CATALOG_PERMISSIONS
    assert "inventory.goods_receipt.post" in CATALOG_PERMISSIONS
    assert "inventory.quality_inspection.create" in CATALOG_PERMISSIONS
    assert "inventory.quality_inspection.read" in CATALOG_PERMISSIONS
    assert "inventory.quality_inspection.update" in CATALOG_PERMISSIONS
    assert "inventory.quality_inspection.approve" in CATALOG_PERMISSIONS
    assert "inventory.delivery_note.create" in CATALOG_PERMISSIONS
    assert "inventory.delivery_note.read" in CATALOG_PERMISSIONS
    assert "inventory.delivery_note.update" in CATALOG_PERMISSIONS
    assert "inventory.delivery_note.delete" in CATALOG_PERMISSIONS
    assert "inventory.delivery_note.post" in CATALOG_PERMISSIONS
    assert "inventory.package.create" in CATALOG_PERMISSIONS
    assert "inventory.package.read" in CATALOG_PERMISSIONS
    assert "inventory.package.update" in CATALOG_PERMISSIONS
    assert "inventory.package.delete" in CATALOG_PERMISSIONS
    assert "inventory.shipment.create" in CATALOG_PERMISSIONS
    assert "inventory.shipment.dispatch" in CATALOG_PERMISSIONS
    assert "inventory.shipment.close" in CATALOG_PERMISSIONS
    assert "inventory.sales_return.create" in CATALOG_PERMISSIONS
    assert "inventory.sales_return.post" in CATALOG_PERMISSIONS
    assert "inventory.product.history" in CATALOG_PERMISSIONS
    assert "crm.customer.history" in CATALOG_PERMISSIONS
    assert "erp.supplier.history" in CATALOG_PERMISSIONS

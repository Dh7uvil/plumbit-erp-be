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
    assert "identity.attachment.delete" in IDENTITY_PERMISSIONS


def test_catalog_includes_quote_ready_permissions() -> None:
    assert "crm.customer.create" in CATALOG_PERMISSIONS
    assert "crm.contact.read" in CATALOG_PERMISSIONS
    assert "inventory.product.create" in CATALOG_PERMISSIONS
    assert "inventory.price_list.update" in CATALOG_PERMISSIONS
    assert "inventory.warehouse.create" in CATALOG_PERMISSIONS
    assert "erp.currency.read" in CATALOG_PERMISSIONS
    assert "erp.exchange_rate.create" in CATALOG_PERMISSIONS
    assert "erp.tax.read" in CATALOG_PERMISSIONS
    assert "erp.quotation.approve" in CATALOG_PERMISSIONS
    assert "erp.quotation.send" in CATALOG_PERMISSIONS
    assert "erp.document_sequence.create" in CATALOG_PERMISSIONS

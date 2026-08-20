"""Unit tests for the identity permission catalog."""

from app.auth.catalog import IDENTITY_PERMISSIONS


def test_catalog_includes_organization_and_audit_permissions() -> None:
    assert "identity.user.read" in IDENTITY_PERMISSIONS
    assert "identity.organization.read" in IDENTITY_PERMISSIONS
    assert "identity.organization.update" in IDENTITY_PERMISSIONS
    assert "identity.branch.create" in IDENTITY_PERMISSIONS
    assert "identity.department.delete" in IDENTITY_PERMISSIONS
    assert "identity.employee.update" in IDENTITY_PERMISSIONS
    assert "identity.audit_log.read" in IDENTITY_PERMISSIONS
    assert "identity.permission.read" in IDENTITY_PERMISSIONS

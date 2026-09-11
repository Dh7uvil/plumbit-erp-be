"""Unit tests for activity changed-field allowlists."""

from app.common.activity.entities import get_activity_spec
from app.common.services.audit import audit_field_changes


def test_quotation_allowlist_drops_unlisted_fields() -> None:
    spec = get_activity_spec("quotation")
    assert spec is not None
    changes = audit_field_changes(
        {"status": "DRAFT", "password": "secret", "quote_number": "QUO-1"},
        {"status": "SENT", "password": "other", "quote_number": "QUO-1"},
    )
    visible = [item["field"] for item in changes if item["field"] in spec.changed_fields]
    assert visible == ["status"]
    assert "password" not in spec.changed_fields


def test_unregistered_entity_type_has_no_spec() -> None:
    assert get_activity_spec("lead") is None


def test_customer_and_supplier_payments_are_registered() -> None:
    for entity_type in ("customer_payment", "supplier_payment"):
        spec = get_activity_spec(entity_type)
        assert spec is not None
        assert "status" in spec.changed_fields


def test_sales_invoice_is_registered() -> None:
    spec = get_activity_spec("sales_invoice")
    assert spec is not None
    assert "status" in spec.changed_fields


def test_credit_and_debit_notes_are_registered() -> None:
    for entity_type in ("credit_note", "debit_note"):
        spec = get_activity_spec(entity_type)
        assert spec is not None
        assert "status" in spec.changed_fields


def test_delivery_note_family_is_registered() -> None:
    for entity_type in ("delivery_note", "sales_return", "package", "shipment"):
        spec = get_activity_spec(entity_type)
        assert spec is not None
        assert "status" in spec.changed_fields

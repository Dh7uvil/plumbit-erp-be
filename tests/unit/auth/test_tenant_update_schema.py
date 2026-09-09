"""TenantCurrentUpdate accepts org-settings form payloads."""

from uuid import uuid4

from pydantic import ValidationError

from app.auth.schemas import TenantCurrentUpdate


def test_blank_optional_fields_are_omitted() -> None:
    payload = TenantCurrentUpdate.model_validate(
        {
            "timezone": "",
            "fiscal_year_start": "  ",
            "default_currency": " inr ",
            "default_currency_id": "none",
            "contact_email": "",
        }
    )
    assert payload.timezone is None
    assert payload.fiscal_year_start is None
    assert payload.default_currency == "INR"
    assert payload.default_currency_id is None
    assert payload.contact_email is None


def test_regional_form_payload_is_valid() -> None:
    currency_id = uuid4()
    payload = TenantCurrentUpdate.model_validate(
        {
            "timezone": "Asia/Kolkata",
            "fiscal_year_start": "April 1",
            "default_currency": "INR",
            "default_currency_id": str(currency_id),
            "quotation_requires_approval": True,
            "allow_negative_stock": False,
        }
    )
    assert payload.timezone == "Asia/Kolkata"
    assert payload.default_currency_id == currency_id
    assert payload.allow_negative_stock is False


def test_inbound_settings_payload_is_valid() -> None:
    payload = TenantCurrentUpdate.model_validate(
        {
            "costing_method": "FIFO",
            "allow_over_receipt": True,
            "over_receipt_tolerance_pct": "5.00",
            "qc_required_default": True,
        }
    )
    assert payload.costing_method is not None
    assert payload.costing_method.value == "FIFO"
    assert payload.allow_over_receipt is True
    assert payload.qc_required_default is True


def test_invalid_contact_email_is_rejected() -> None:
    try:
        TenantCurrentUpdate.model_validate({"contact_email": "info"})
    except ValidationError as exc:
        assert "contact_email" in str(exc)
        return
    raise AssertionError("expected contact_email validation to fail")

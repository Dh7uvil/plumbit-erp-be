"""Unit tests for the proforma invoice status machine."""

import pytest

from app.core.enums import ProformaInvoiceStatus
from app.core.exceptions import InvalidStatusTransitionError
from app.erp.proforma_invoices.workflow import (
    assert_convertible,
    assert_editable,
    next_status,
    transition_actions,
)


def test_happy_path_send_confirm_convert() -> None:
    status = ProformaInvoiceStatus.DRAFT
    status = next_status(status, "send")
    assert status == ProformaInvoiceStatus.SENT
    status = next_status(status, "confirm")
    assert status == ProformaInvoiceStatus.CONFIRMED
    status = next_status(status, "convert")
    assert status == ProformaInvoiceStatus.CONVERTED


def test_sent_can_revise_and_decline() -> None:
    assert next_status(ProformaInvoiceStatus.SENT, "revise") == ProformaInvoiceStatus.DRAFT
    assert next_status(ProformaInvoiceStatus.SENT, "decline") == ProformaInvoiceStatus.DECLINED
    assert next_status(ProformaInvoiceStatus.DECLINED, "reopen") == ProformaInvoiceStatus.DRAFT


def test_expired_can_revise_or_cancel() -> None:
    assert next_status(ProformaInvoiceStatus.EXPIRED, "revise") == ProformaInvoiceStatus.DRAFT
    assert next_status(ProformaInvoiceStatus.EXPIRED, "cancel") == ProformaInvoiceStatus.CANCELLED


def test_only_draft_is_editable() -> None:
    assert_editable(ProformaInvoiceStatus.DRAFT)
    with pytest.raises(InvalidStatusTransitionError):
        assert_editable(ProformaInvoiceStatus.SENT)


def test_only_confirmed_or_partially_converted_is_convertible() -> None:
    assert_convertible(ProformaInvoiceStatus.CONFIRMED)
    assert_convertible(ProformaInvoiceStatus.PARTIALLY_CONVERTED)
    with pytest.raises(InvalidStatusTransitionError):
        assert_convertible(ProformaInvoiceStatus.SENT)
    assert next_status(ProformaInvoiceStatus.CONFIRMED, "convert") == (
        ProformaInvoiceStatus.CONVERTED
    )
    assert next_status(ProformaInvoiceStatus.PARTIALLY_CONVERTED, "convert") == (
        ProformaInvoiceStatus.CONVERTED
    )


def test_transition_actions_follow_the_machine() -> None:
    assert transition_actions(ProformaInvoiceStatus.DRAFT) == ["send", "cancel"]
    assert transition_actions(ProformaInvoiceStatus.SENT) == [
        "confirm",
        "decline",
        "revise",
        "cancel",
    ]
    assert transition_actions(ProformaInvoiceStatus.CONFIRMED) == ["convert", "cancel"]
    assert transition_actions(ProformaInvoiceStatus.EXPIRED) == ["revise", "cancel"]

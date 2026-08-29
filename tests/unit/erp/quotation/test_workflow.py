"""Unit tests for the quotation status machine."""

import pytest

from app.core.enums import QuotationStatus
from app.core.exceptions import InvalidStatusTransitionError
from app.erp.quotation.workflow import assert_editable, next_status


def test_happy_path_submit_approve_send_accept() -> None:
    status = QuotationStatus.DRAFT
    status = next_status(status, "submit")
    assert status == QuotationStatus.PENDING_APPROVAL
    status = next_status(status, "approve")
    assert status == QuotationStatus.APPROVED
    status = next_status(status, "send")
    assert status == QuotationStatus.SENT
    status = next_status(status, "accept")
    assert status == QuotationStatus.ACCEPTED


def test_accepted_cannot_return_to_draft() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        next_status(QuotationStatus.ACCEPTED, "reopen")


def test_cannot_accept_from_pending_approval() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        next_status(QuotationStatus.PENDING_APPROVAL, "accept")


def test_only_draft_is_editable() -> None:
    assert_editable(QuotationStatus.DRAFT)
    with pytest.raises(InvalidStatusTransitionError):
        assert_editable(QuotationStatus.SENT)

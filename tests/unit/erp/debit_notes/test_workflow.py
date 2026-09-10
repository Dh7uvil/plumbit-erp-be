"""Unit tests for debit note status transitions."""

import pytest

from app.core.enums import InvoiceDocumentStatus
from app.core.exceptions import InvalidStatusTransitionError
from app.erp.debit_notes.workflow import assert_editable, next_status, transition_actions


def test_draft_can_post_or_cancel() -> None:
    assert set(transition_actions(InvoiceDocumentStatus.DRAFT)) == {"post", "cancel"}
    assert next_status(InvoiceDocumentStatus.DRAFT, "post") == InvoiceDocumentStatus.POSTED
    assert next_status(InvoiceDocumentStatus.POSTED, "cancel") == InvoiceDocumentStatus.CANCELLED


def test_posted_cannot_be_edited() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        assert_editable(InvoiceDocumentStatus.POSTED)

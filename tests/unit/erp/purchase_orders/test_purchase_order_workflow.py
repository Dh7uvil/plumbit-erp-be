"""Unit tests for the purchase order status machine."""

import pytest

from app.core.enums import PurchaseOrderStatus
from app.core.exceptions import InvalidStatusTransitionError
from app.erp.purchase_orders.workflow import assert_editable, next_status, transition_actions


def test_happy_path_submit_approve_issue_close() -> None:
    status = PurchaseOrderStatus.DRAFT
    status = next_status(status, "submit")
    assert status == PurchaseOrderStatus.PENDING_APPROVAL
    status = next_status(status, "approve")
    assert status == PurchaseOrderStatus.APPROVED
    status = next_status(status, "issue")
    assert status == PurchaseOrderStatus.ISSUED
    status = next_status(status, "close")
    assert status == PurchaseOrderStatus.CLOSED


def test_draft_can_issue_directly() -> None:
    assert next_status(PurchaseOrderStatus.DRAFT, "issue") == PurchaseOrderStatus.ISSUED


def test_issued_cannot_return_to_draft() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        next_status(PurchaseOrderStatus.ISSUED, "reopen")


def test_closed_reopens_to_issued() -> None:
    assert next_status(PurchaseOrderStatus.CLOSED, "reopen") == PurchaseOrderStatus.ISSUED


def test_only_draft_is_editable() -> None:
    assert_editable(PurchaseOrderStatus.DRAFT)
    with pytest.raises(InvalidStatusTransitionError):
        assert_editable(PurchaseOrderStatus.ISSUED)


def test_transition_actions_follow_the_machine() -> None:
    assert transition_actions(PurchaseOrderStatus.DRAFT) == ["submit", "issue", "cancel"]
    assert transition_actions(PurchaseOrderStatus.PENDING_APPROVAL) == [
        "approve",
        "reject",
        "cancel",
    ]
    assert transition_actions(PurchaseOrderStatus.ISSUED) == ["close", "cancel"]

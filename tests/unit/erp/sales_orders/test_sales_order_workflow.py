"""Unit tests for the sales order status machine."""

import pytest

from app.core.enums import SalesOrderStatus
from app.core.exceptions import InvalidStatusTransitionError
from app.erp.sales_orders.workflow import assert_editable, next_status, transition_actions


def test_happy_path_submit_approve_confirm_close() -> None:
    status = SalesOrderStatus.DRAFT
    status = next_status(status, "submit")
    assert status == SalesOrderStatus.PENDING_APPROVAL
    status = next_status(status, "approve")
    assert status == SalesOrderStatus.APPROVED
    status = next_status(status, "confirm")
    assert status == SalesOrderStatus.CONFIRMED
    status = next_status(status, "close")
    assert status == SalesOrderStatus.CLOSED


def test_draft_can_confirm_directly() -> None:
    assert next_status(SalesOrderStatus.DRAFT, "confirm") == SalesOrderStatus.CONFIRMED


def test_confirmed_cannot_return_to_draft() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        next_status(SalesOrderStatus.CONFIRMED, "reopen")


def test_closed_reopens_to_confirmed() -> None:
    assert next_status(SalesOrderStatus.CLOSED, "reopen") == SalesOrderStatus.CONFIRMED


def test_only_draft_is_editable() -> None:
    assert_editable(SalesOrderStatus.DRAFT)
    with pytest.raises(InvalidStatusTransitionError):
        assert_editable(SalesOrderStatus.CONFIRMED)


def test_transition_actions_follow_the_machine() -> None:
    assert transition_actions(SalesOrderStatus.DRAFT) == ["submit", "confirm", "cancel"]
    assert transition_actions(SalesOrderStatus.PENDING_APPROVAL) == [
        "approve",
        "reject",
        "cancel",
    ]
    assert transition_actions(SalesOrderStatus.CONFIRMED) == ["close", "cancel"]

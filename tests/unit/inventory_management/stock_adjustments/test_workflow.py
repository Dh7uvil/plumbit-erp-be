"""Stock adjustment status machine."""

import pytest

from app.core.enums import StockDocumentStatus
from app.core.exceptions import InvalidStatusTransitionError
from app.inventory_management.stock_adjustments.workflow import (
    assert_editable,
    next_status,
    transition_actions,
)


def test_draft_actions() -> None:
    assert transition_actions(StockDocumentStatus.DRAFT) == ["post", "cancel"]


def test_posted_has_no_transitions() -> None:
    assert transition_actions(StockDocumentStatus.POSTED) == []
    assert transition_actions(StockDocumentStatus.CANCELLED) == []


def test_post_and_cancel() -> None:
    assert next_status(StockDocumentStatus.DRAFT, "post") == StockDocumentStatus.POSTED
    assert next_status(StockDocumentStatus.DRAFT, "cancel") == StockDocumentStatus.CANCELLED


def test_cannot_post_posted() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        next_status(StockDocumentStatus.POSTED, "post")


def test_assert_editable() -> None:
    assert_editable(StockDocumentStatus.DRAFT)
    with pytest.raises(InvalidStatusTransitionError):
        assert_editable(StockDocumentStatus.POSTED)

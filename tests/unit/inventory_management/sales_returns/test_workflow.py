"""Unit tests for sales return status transitions."""

import pytest

from app.core.enums import StockDocumentStatus
from app.core.exceptions import InvalidStatusTransitionError
from app.inventory_management.sales_returns.workflow import (
    assert_editable,
    next_status,
    transition_actions,
)


def test_draft_can_post_or_cancel() -> None:
    assert set(transition_actions(StockDocumentStatus.DRAFT)) == {"post", "cancel"}
    assert next_status(StockDocumentStatus.DRAFT, "post") == StockDocumentStatus.POSTED
    assert next_status(StockDocumentStatus.POSTED, "cancel") == StockDocumentStatus.CANCELLED


def test_posted_cannot_be_edited() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        assert_editable(StockDocumentStatus.POSTED)

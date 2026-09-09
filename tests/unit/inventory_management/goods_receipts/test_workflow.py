"""Unit tests for goods receipt status and over-receipt."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.enums import StockDocumentStatus
from app.core.exceptions import GrnOverReceiptError, InvalidStatusTransitionError
from app.inventory_management.goods_receipts.service import GoodsReceiptService
from app.inventory_management.goods_receipts.workflow import (
    assert_editable,
    next_status,
    transition_actions,
)


def test_draft_can_post_or_cancel() -> None:
    assert transition_actions(StockDocumentStatus.DRAFT) == ["post", "cancel"]
    assert next_status(StockDocumentStatus.DRAFT, "post") == StockDocumentStatus.POSTED
    assert next_status(StockDocumentStatus.POSTED, "cancel") == StockDocumentStatus.CANCELLED


def test_posted_cannot_be_edited() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        assert_editable(StockDocumentStatus.POSTED)


def test_over_receipt_blocked_when_disallowed() -> None:
    service = GoodsReceiptService.__new__(GoodsReceiptService)
    line = SimpleNamespace(line_number=1, quantity=Decimal("11"))
    with pytest.raises(GrnOverReceiptError):
        service._assert_over_receipt_qty(
            line, remaining=Decimal("10"), allow_over=False, tolerance_pct=None
        )


def test_over_receipt_within_tolerance_is_allowed() -> None:
    service = GoodsReceiptService.__new__(GoodsReceiptService)
    line = SimpleNamespace(line_number=1, quantity=Decimal("11"))
    service._assert_over_receipt_qty(
        line, remaining=Decimal("10"), allow_over=True, tolerance_pct=Decimal("20")
    )


def test_unlimited_over_receipt_when_tolerance_is_null() -> None:
    service = GoodsReceiptService.__new__(GoodsReceiptService)
    line = SimpleNamespace(line_number=1, quantity=Decimal("100"))
    service._assert_over_receipt_qty(
        line, remaining=Decimal("10"), allow_over=True, tolerance_pct=None
    )

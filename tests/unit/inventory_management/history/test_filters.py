"""Trading history filter allowlists."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.inventory_management.history.schemas import TradingAggregateFilter, TradingHistoryFilter


def test_trading_history_sort_allowlist() -> None:
    TradingHistoryFilter(sort_by="quantity", sort_order="desc", search="DN-1")
    with pytest.raises(ValidationError):
        TradingHistoryFilter(sort_by="not_a_field")


def test_trading_aggregate_sort_allowlist() -> None:
    TradingAggregateFilter(sort_by="party_name", search="Acme")
    TradingAggregateFilter(sort_by="sku")
    with pytest.raises(ValidationError):
        TradingAggregateFilter(sort_by="secret")

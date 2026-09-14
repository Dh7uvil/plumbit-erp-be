import pytest
from pydantic import ValidationError

from app.inventory_management.stock.schemas import StockFilter
from app.inventory_management.units.schemas import UnitFilter


def test_subclass_sort_allowlist_is_enforced() -> None:
    UnitFilter(sort_by="is_active")
    with pytest.raises(ValidationError, match="sort_by must be one of"):
        UnitFilter(sort_by="foobar")


def test_stock_filter_rejects_sku_sort() -> None:
    StockFilter(sort_by="qty_on_hand")
    with pytest.raises(ValidationError, match="sort_by must be one of"):
        StockFilter(sort_by="sku")

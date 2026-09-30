"""Unit tests for Phase 4 inventory integrity guardrails."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.enums import StockMovementType
from app.core.exceptions import InsufficientStockError, ValidationError
from app.inventory_management.costing.repository import CostingRepository
from app.inventory_management.stock.service import StockService
from app.inventory_management.stock_adjustments.schemas import StockAdjustmentLineInput


def _locked(
    *,
    on_hand: str = "10",
    reserved: str = "0",
    hold: str = "0",
    allow_negative: bool = False,
):
    return SimpleNamespace(
        row=SimpleNamespace(
            qty_on_hand=Decimal(on_hand),
            qty_reserved=Decimal(reserved),
            qty_quality_hold=Decimal(hold),
        ),
        warehouse=SimpleNamespace(id=uuid4(), code="WH1"),
        product=SimpleNamespace(id=uuid4(), unit_id=uuid4()),
        allow_negative_stock=allow_negative,
    )


@pytest.mark.asyncio
async def test_delete_layers_for_source_rejects_partially_consumed() -> None:
    repo = CostingRepository.__new__(CostingRepository)
    layer = SimpleNamespace(
        id=uuid4(),
        qty_remaining=Decimal("3"),
        qty_received=Decimal("10"),
    )

    async def _list_layers(*_args, **_kwargs):
        return [layer]

    repo.list_layers_for_source = _list_layers  # type: ignore[method-assign]

    with pytest.raises(ValidationError, match="partially consumed"):
        await repo.delete_layers_for_source(uuid4(), "goods_receipt", uuid4())


@pytest.mark.asyncio
async def test_apply_quality_hold_cannot_exceed_on_hand() -> None:
    service = StockService.__new__(StockService)
    service.session = SimpleNamespace(flush=lambda: None)
    service.movements = SimpleNamespace(create=lambda *_a, **_k: None)

    locked = _locked(on_hand="5", hold="2")
    with pytest.raises(ValidationError, match="exceed on-hand"):
        await service.apply_quality_hold_locked(
            uuid4(),
            locked,
            qty=Decimal("4"),
            movement_type=StockMovementType.QC_HOLD,
            source_type="quality_inspection",
            source_id=uuid4(),
            source_line_id=None,
            document_date=SimpleNamespace(),
            notes=None,
        )


@pytest.mark.asyncio
async def test_reserve_locked_checks_available_qty() -> None:
    service = StockService.__new__(StockService)
    service.session = SimpleNamespace(flush=lambda: None)

    locked = _locked(on_hand="10", reserved="8", hold="1")
    with pytest.raises(InsufficientStockError):
        await service.reserve_locked(locked, qty=Decimal("2"))


@pytest.mark.asyncio
async def test_reverse_inbound_locked_checks_available_qty() -> None:
    service = StockService.__new__(StockService)
    service.costing = SimpleNamespace(
        delete_layers_for_source=lambda *_a, **_k: None,
        assert_balanced=lambda *_a, **_k: None,
    )
    service.session = SimpleNamespace(flush=lambda: None)
    service.movements = SimpleNamespace(create=lambda *_a, **_k: SimpleNamespace())

    locked = _locked(on_hand="5", reserved="4", hold="1")
    with pytest.raises(InsufficientStockError):
        await service.reverse_inbound_locked(
            uuid4(),
            locked,
            qty=Decimal("2"),
            movement_type=StockMovementType.PURCHASE,
            source_type="goods_receipt",
            source_id=uuid4(),
            source_line_id=None,
            document_date=SimpleNamespace(),
            notes=None,
        )


@pytest.mark.asyncio
async def test_reconsume_outbound_locked_checks_available_qty() -> None:
    service = StockService.__new__(StockService)
    service.movements = SimpleNamespace(
        list_for_source=lambda *_a, **_k: [SimpleNamespace(qty=Decimal("-1"))],
        create=lambda *_a, **_k: SimpleNamespace(),
    )
    service.costing = SimpleNamespace(
        unrestore_partial=lambda *_a, **_k: [],
        assert_balanced=lambda *_a, **_k: None,
    )
    service.session = SimpleNamespace(flush=lambda: None)

    locked = _locked(on_hand="5", reserved="4", hold="1")
    with pytest.raises(InsufficientStockError):
        await service.reconsume_outbound_locked(
            uuid4(),
            locked,
            qty=Decimal("2"),
            movement_type=StockMovementType.DAMAGE,
            source_type="sales_return",
            source_id=uuid4(),
            source_line_id=None,
            document_date=SimpleNamespace(),
            notes=None,
        )


def test_positive_stock_adjustment_requires_unit_cost() -> None:
    with pytest.raises(PydanticValidationError, match="unit_cost"):
        StockAdjustmentLineInput(product_id=uuid4(), qty_delta=Decimal("1"))

    line = StockAdjustmentLineInput(
        product_id=uuid4(),
        qty_delta=Decimal("1"),
        unit_cost=Decimal("10"),
    )
    assert line.unit_cost == Decimal("10")


@pytest.mark.asyncio
async def test_category_create_requires_active_parent(monkeypatch) -> None:
    from app.inventory_management.categories.service import CategoryService

    service = CategoryService.__new__(CategoryService)
    parent_id = uuid4()

    async def _require_id(_tenant_id, category_id):
        if category_id == parent_id:
            raise ValidationError("Category is inactive")

    service.require_id = _require_id  # type: ignore[method-assign]
    service.repo = SimpleNamespace()
    service.audit = SimpleNamespace(write=lambda *_a, **_k: None)
    service.session = SimpleNamespace()
    service._validate_account_refs = lambda *_a, **_k: None  # type: ignore[method-assign]

    def _transaction(_session):
        class _Ctx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

        return _Ctx()

    monkeypatch.setattr("app.inventory_management.categories.service.transaction", _transaction)

    from app.inventory_management.categories.schemas import CategoryCreate

    with pytest.raises(ValidationError, match="inactive"):
        await service.create(
            uuid4(),
            CategoryCreate(name="Child", code="CHILD", parent_id=parent_id),
            actor_user_id=uuid4(),
        )

"""Unit coverage for concurrent document posting uniqueness recovery."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.enums import JournalType
from app.erp.accounting.ledger.posting import LedgerPostingService
from app.erp.accounting.ledger.schemas import JournalLineInput


class _NullCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


@pytest.mark.asyncio
async def test_post_for_document_returns_existing_on_unique_violation(monkeypatch) -> None:
    existing = SimpleNamespace(id=uuid4(), lines=[])
    lookups = {"count": 0}
    creates = {"count": 0}

    class Repo:
        async def get_posted_for_source(self, *_args, **_kwargs):
            lookups["count"] += 1
            if lookups["count"] == 1:
                return None
            return existing

        async def create(self, *_args, **_kwargs):
            creates["count"] += 1
            raise IntegrityError("duplicate", params=None, orig=Exception("uq"))

        async def replace_lines(self, *_args, **_kwargs) -> None:
            return None

        async def get(self, *_args, **_kwargs):
            return existing

    service = LedgerPostingService.__new__(LedgerPostingService)
    service.repo = Repo()
    service._can_override = False
    service.session = SimpleNamespace(begin_nested=lambda: _NullCtx())

    async def _prepare(*_args, **_kwargs):
        return [
            SimpleNamespace(debit_base=Decimal("10"), credit_base=Decimal("0")),
            SimpleNamespace(debit_base=Decimal("0"), credit_base=Decimal("10")),
        ]

    async def _assert_books_started(*_args, **_kwargs) -> None:
        return None

    async def _controls(*_args, **_kwargs):
        return True, SimpleNamespace(assert_open=lambda *_a, **_k: None)

    async def _allocate(*_args, **_kwargs) -> str:
        return "JV-1"

    async def _year_for(*_args, **_kwargs) -> int:
        return 2026

    service._prepare_lines = _prepare  # type: ignore[method-assign]
    service._assert_books_started = _assert_books_started  # type: ignore[method-assign]
    service.org = SimpleNamespace(get_inventory_controls=_controls)
    service.sequences = SimpleNamespace(allocate=_allocate)
    monkeypatch.setattr("app.erp.accounting.ledger.posting.year_for", _year_for)

    result = await service.post_for_document(
        uuid4(),
        source_type="sales_invoice",
        source_id=uuid4(),
        entry_date=date(2026, 1, 15),
        lines=[
            JournalLineInput(account_id=uuid4(), debit=Decimal("10"), credit=Decimal("0")),
            JournalLineInput(account_id=uuid4(), debit=Decimal("0"), credit=Decimal("10")),
        ],
        currency_id=uuid4(),
        exchange_rate=Decimal("1"),
        narration="race",
        branch_id=None,
        actor_id=uuid4(),
        journal_type=JournalType.SYSTEM,
    )
    assert result is existing
    assert creates["count"] == 1
    assert lookups["count"] == 2

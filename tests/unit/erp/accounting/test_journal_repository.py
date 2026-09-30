"""Unit tests for journal entry repository queries."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.erp.accounting.ledger.repository import JournalEntryRepository


class _CaptureSession:
    def __init__(self) -> None:
        self.statement = None

    async def execute(self, statement):
        self.statement = statement

        class _Result:
            @staticmethod
            def scalar_one_or_none():
                return None

        return _Result()


@pytest.mark.asyncio
async def test_get_posted_for_source_excludes_reversed() -> None:
    session = _CaptureSession()
    repo = JournalEntryRepository(session)  # type: ignore[arg-type]
    tenant_id = uuid4()
    source_id = uuid4()

    await repo.get_posted_for_source(tenant_id, "sales_invoice", source_id)

    assert session.statement is not None
    compiled = str(session.statement.compile(compile_kwargs={"literal_binds": True}))
    assert "reversed_by_id IS NULL" in compiled

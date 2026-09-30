"""GL integrity scan response schemas."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class GlIntegrityIssue(BaseModel):
    kind: Literal["unbalanced_journal", "trial_balance", "control_vs_subledger"]
    message: str
    journal_id: UUID | None = None
    document_number: str | None = None
    debit: Decimal | None = None
    credit: Decimal | None = None
    party_type: str | None = None
    party_id: UUID | None = None
    party_name: str | None = None
    gl_balance: Decimal | None = None
    subledger_balance: Decimal | None = None
    variance: Decimal | None = None


class GlIntegrityResponse(BaseModel):
    as_of: date
    ok: bool
    issue_count: int
    issues: list[GlIntegrityIssue]

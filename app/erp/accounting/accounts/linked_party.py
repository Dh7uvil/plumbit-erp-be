"""Party link metadata for AR/AP control accounts."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.core.enums import PartyType


@dataclass(frozen=True, slots=True)
class LinkedParty:
    party_id: UUID
    party_name: str
    party_type: PartyType

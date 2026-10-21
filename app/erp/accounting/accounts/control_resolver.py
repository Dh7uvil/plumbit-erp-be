"""Resolve party context for AR/AP control accounts on journal lines."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AccountSubtype, PartyType
from app.core.exceptions import PartyRequiredForControlAccountError
from app.erp.accounting.accounts.linked_party import LinkedParty
from app.erp.accounting.accounts.models import Account
from app.erp.accounting.accounts.repository import AccountRepository

_CONTROL_SUBTYPES = frozenset(
    {AccountSubtype.ACCOUNTS_RECEIVABLE.value, AccountSubtype.ACCOUNTS_PAYABLE.value}
)


class ControlAccountResolver:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = AccountRepository(session)

    async def find_linked_party(
        self, tenant_id: UUID, account: Account
    ) -> LinkedParty | None:
        parties = await self.repo.find_parties_linked_to_account(
            tenant_id, account.id, account_subtype=account.account_subtype
        )
        if len(parties) != 1:
            return None
        return parties[0]

    async def resolve_line_party(
        self,
        tenant_id: UUID,
        account: Account,
        *,
        party_type: PartyType | str | None,
        party_id: UUID | None,
        line_number: int | None = None,
    ) -> tuple[PartyType | None, UUID | None]:
        if account.account_subtype not in _CONTROL_SUBTYPES:
            pt = PartyType(party_type) if isinstance(party_type, str) and party_type else party_type
            return pt if isinstance(pt, PartyType) else None, party_id
        if party_id is not None:
            pt = PartyType(party_type) if isinstance(party_type, str) and party_type else party_type
            return pt if isinstance(pt, PartyType) else None, party_id
        linked = await self.find_linked_party(tenant_id, account)
        if linked is not None:
            return linked.party_type, linked.party_id
        if account.is_standalone_ledger:
            return None, None
        raise PartyRequiredForControlAccountError(
            details={
                "account_id": str(account.id),
                "line_number": line_number,
            }
        )

    async def assert_assignable_ar_ap(self, tenant_id: UUID, account: Account) -> None:
        """Charge types and similar masters may only reference usable AR/AP ledgers."""
        if account.account_subtype not in _CONTROL_SUBTYPES:
            return
        if account.is_standalone_ledger:
            return
        linked = await self.find_linked_party(tenant_id, account)
        if linked is not None:
            return
        from app.core.exceptions import ValidationError

        raise ValidationError(
            "AR/AP accounts must be standalone ledgers or linked to a customer or supplier",
            details={"account_id": str(account.id)},
        )

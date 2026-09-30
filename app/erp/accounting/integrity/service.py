"""GL integrity checks: balanced journals, trial balance, and control vs sub-ledger."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.org_service import OrganizationService
from app.common.utils.currency import quantize_money
from app.common.utils.datetime import today_in_timezone
from app.core.enums import (
    CompanyType,
    FxRevaluationStatus,
    JournalEntryStatus,
    OpenItemType,
    PartyType,
)
from app.core.exceptions import (
    AccountNotPostableError,
    AccountRoleUnmappedError,
    ResourceNotFoundError,
    ValidationError,
)
from app.crm.customers.models import Customer
from app.db.session import transaction
from app.erp.accounting.accounts.service import PartyAccountResolver
from app.erp.accounting.fx_revaluation.models import FxRevaluationLine, FxRevaluationRun
from app.erp.accounting.integrity.schemas import GlIntegrityIssue, GlIntegrityResponse
from app.erp.accounting.ledger.models import JournalEntry, JournalEntryLine
from app.erp.accounting.open_items.as_of import AsOfOpenItem, as_of_balances
from app.erp.accounting.reports.amounts import open_item_base_amount
from app.erp.accounting.reports.service import ReportService

_TOLERANCE = Decimal("0.0100")


class GlIntegrityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def scan(self, tenant_id: UUID, *, as_of: date | None = None) -> GlIntegrityResponse:
        if as_of is None:
            timezone = await OrganizationService(self.session).get_timezone(tenant_id)
            as_of = today_in_timezone(timezone)
        issues: list[GlIntegrityIssue] = []
        async with transaction(self.session):
            unbalanced = (
                await self.session.execute(
                    select(
                        JournalEntry.id,
                        JournalEntry.document_number,
                        func.coalesce(func.sum(JournalEntryLine.debit_base), 0),
                        func.coalesce(func.sum(JournalEntryLine.credit_base), 0),
                    )
                    .join(
                        JournalEntryLine,
                        JournalEntryLine.journal_entry_id == JournalEntry.id,
                    )
                    .where(
                        JournalEntry.tenant_id == tenant_id,
                        JournalEntry.deleted_at.is_(None),
                        JournalEntry.status == JournalEntryStatus.POSTED.value,
                    )
                    .group_by(JournalEntry.id, JournalEntry.document_number)
                    .having(
                        func.coalesce(func.sum(JournalEntryLine.debit_base), 0)
                        != func.coalesce(func.sum(JournalEntryLine.credit_base), 0)
                    )
                )
            ).all()
            for journal_id, document_number, debit, credit in unbalanced:
                issues.append(
                    GlIntegrityIssue(
                        kind="unbalanced_journal",
                        message=(
                            f"unbalanced journal {document_number} ({journal_id}): "
                            f"debit={debit} credit={credit}"
                        ),
                        journal_id=journal_id,
                        document_number=document_number,
                        debit=Decimal(debit),
                        credit=Decimal(credit),
                    )
                )

            trial = await ReportService(self.session).trial_balance(
                tenant_id,
                from_date=date(1900, 1, 1),
                to_date=as_of,
                include_zero=True,
            )
            if not trial.is_balanced:
                issues.append(
                    GlIntegrityIssue(
                        kind="trial_balance",
                        message=(
                            "trial balance out of balance: "
                            f"debit={trial.total_closing_debit} "
                            f"credit={trial.total_closing_credit}"
                        ),
                        debit=trial.total_closing_debit,
                        credit=trial.total_closing_credit,
                    )
                )

            issues.extend(await self._control_vs_subledger(tenant_id, as_of=as_of))

        return GlIntegrityResponse(
            as_of=as_of,
            ok=not issues,
            issue_count=len(issues),
            issues=issues,
        )

    async def _control_vs_subledger(
        self, tenant_id: UUID, *, as_of: date
    ) -> list[GlIntegrityIssue]:
        issues: list[GlIntegrityIssue] = []
        parties = await self._parties(tenant_id)
        names = {party.id: party.name for party in parties}
        resolver = PartyAccountResolver(self.session)
        reports = ReportService(self.session)
        ar_items = await as_of_balances(self.session, tenant_id, PartyType.CUSTOMER, as_of)
        ap_items = await as_of_balances(self.session, tenant_id, PartyType.SUPPLIER, as_of)
        ar_by_party = _group_by_party(ar_items)
        ap_by_party = _group_by_party(ap_items)
        fx_variances = await self._fx_variances_by_party(tenant_id, as_of=as_of)

        for party_type, grouped in (
            (PartyType.CUSTOMER, ar_by_party),
            (PartyType.SUPPLIER, ap_by_party),
        ):
            company_types = (
                (CompanyType.CUSTOMER.value, CompanyType.BOTH.value)
                if party_type == PartyType.CUSTOMER
                else (CompanyType.SUPPLIER.value, CompanyType.BOTH.value)
            )
            for party in parties:
                if party.company_type not in company_types:
                    continue
                items = grouped.get(party.id, [])
                subledger = _subledger_net(items, party_type=party_type)
                try:
                    if party_type == PartyType.CUSTOMER:
                        account = await resolver.resolve_receivable(tenant_id, party.id)
                    else:
                        account = await resolver.resolve_payable(tenant_id, party.id)
                except (
                    ResourceNotFoundError,
                    ValidationError,
                    AccountRoleUnmappedError,
                    AccountNotPostableError,
                ):
                    continue
                gl_map = await reports._sum_by_account(
                    tenant_id,
                    end=as_of,
                    account_id=account.id,
                    party_id=party.id,
                )
                debit, credit = gl_map.get(account.id, (Decimal("0"), Decimal("0")))
                if party_type == PartyType.CUSTOMER:
                    gl_balance = quantize_money(debit - credit)
                else:
                    gl_balance = quantize_money(credit - debit)
                if subledger == Decimal("0") and gl_balance == Decimal("0"):
                    continue
                allowed = abs(fx_variances.get((party_type.value, party.id), Decimal("0")))
                variance = quantize_money(gl_balance - subledger)
                if abs(variance) <= _TOLERANCE + allowed:
                    continue
                issues.append(
                    GlIntegrityIssue(
                        kind="control_vs_subledger",
                        message=(
                            f"{party_type.value} control vs sub-ledger mismatch for "
                            f"{names.get(party.id, party.id)}: gl={gl_balance} "
                            f"subledger={subledger} variance={variance}"
                        ),
                        party_type=party_type.value,
                        party_id=party.id,
                        party_name=names.get(party.id),
                        gl_balance=gl_balance,
                        subledger_balance=subledger,
                        variance=variance,
                    )
                )
        return issues

    async def _parties(self, tenant_id: UUID) -> list[Customer]:
        return list(
            (
                await self.session.execute(
                    select(Customer).where(
                        Customer.tenant_id == tenant_id,
                        Customer.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )

    async def _fx_variances_by_party(
        self, tenant_id: UUID, *, as_of: date
    ) -> dict[tuple[str, UUID], Decimal]:
        statement = (
            select(
                FxRevaluationLine.party_type,
                FxRevaluationLine.party_id,
                func.coalesce(func.sum(FxRevaluationLine.gain_base), 0),
            )
            .join(FxRevaluationRun, FxRevaluationLine.run_id == FxRevaluationRun.id)
            .where(
                FxRevaluationLine.tenant_id == tenant_id,
                FxRevaluationRun.tenant_id == tenant_id,
                FxRevaluationRun.deleted_at.is_(None),
                FxRevaluationRun.status == FxRevaluationStatus.POSTED.value,
                FxRevaluationRun.as_of_date <= as_of,
                FxRevaluationLine.party_id.is_not(None),
                FxRevaluationLine.party_type.is_not(None),
            )
            .group_by(FxRevaluationLine.party_type, FxRevaluationLine.party_id)
        )
        rows = (await self.session.execute(statement)).all()
        return {
            (party_type, party_id): quantize_money(abs(Decimal(str(gain))))
            for party_type, party_id, gain in rows
            if party_type is not None and party_id is not None
        }


def _group_by_party(items: list[AsOfOpenItem]) -> dict[UUID, list[AsOfOpenItem]]:
    grouped: dict[UUID, list[AsOfOpenItem]] = {}
    for item in items:
        grouped.setdefault(item.party_id, []).append(item)
    return grouped


def _subledger_net(items: list[AsOfOpenItem], *, party_type: PartyType) -> Decimal:
    outstanding_types = (
        {OpenItemType.SALES_INVOICE, OpenItemType.OPENING_AR}
        if party_type == PartyType.CUSTOMER
        else {OpenItemType.PURCHASE_INVOICE, OpenItemType.OPENING_AP}
    )
    credit_types = (
        {OpenItemType.CREDIT_NOTE, OpenItemType.CUSTOMER_PAYMENT}
        if party_type == PartyType.CUSTOMER
        else {OpenItemType.DEBIT_NOTE, OpenItemType.SUPPLIER_PAYMENT}
    )
    net = Decimal("0")
    for item in items:
        row = item.to_open_item_row()
        amount = open_item_base_amount(row)
        if amount is None:
            continue
        if item.item_type in credit_types:
            net = quantize_money(net - amount)
        elif item.item_type in outstanding_types:
            net = quantize_money(net + amount)
    return net

"""Go-live opening balances: preview, commit, and reset."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import ERP_MODULE, PERIOD_OVERRIDE
from app.auth.models import Tenant
from app.auth.org_service import OrganizationService
from app.common.idempotency.service import IdempotencyService
from app.common.services.audit import AuditWriter
from app.common.utils.currency import quantize_money, quantize_quantity
from app.core.enums import (
    AccountSystemRole,
    AuditAction,
    JournalEntryStatus,
    JournalType,
    PartyType,
    StockMovementType,
)
from app.core.exceptions import (
    OpeningStockValueMismatchError,
    ResourceNotFoundError,
    ValidationError,
)
from app.core.permissions import has_permission
from app.db.session import transaction
from app.erp.accounting.accounts.service import AccountService
from app.erp.accounting.ledger.models import JournalEntry
from app.erp.accounting.ledger.posting import SOURCE_OPENING_BALANCE, LedgerPostingService
from app.erp.accounting.ledger.repository import JournalEntryRepository
from app.erp.accounting.ledger.schemas import JournalLineInput
from app.erp.accounting.opening_balances.schemas import (
    OpeningBalancePayload,
    OpeningBalancePreviewLine,
    OpeningBalancePreviewResponse,
    OpeningBalanceStateResponse,
)
from app.erp.exchange_rates.service import CurrencyService
from app.inventory_management.stock.service import StockService

_ZERO = Decimal("0")


class OpeningBalanceService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.org = OrganizationService(session)
        self.accounts = AccountService(session)
        self.posting = LedgerPostingService(session, actor_permissions=actor_permissions)
        self.journals = JournalEntryRepository(session)
        self.stock = StockService(session, actor_permissions=actor_permissions)
        self.currencies = CurrencyService(session)
        self.idempotency = IdempotencyService(session)
        self.audit = AuditWriter(session)
        self._can_override = has_permission(actor_permissions, PERIOD_OVERRIDE)

    async def get_state(self, tenant_id: UUID) -> OpeningBalanceStateResponse:
        tenant = await self._require_tenant(tenant_id)
        opening = await self.journals.get_posted_for_source(
            tenant_id, SOURCE_OPENING_BALANCE, tenant_id
        )
        can_reset = False
        if opening is not None and tenant.books_start_date is not None:
            can_reset = not await self._has_activity_after_golive(tenant_id, opening.id)
        return OpeningBalanceStateResponse(
            committed=opening is not None,
            books_start_date=tenant.books_start_date,
            hard_lock_date=tenant.hard_lock_date,
            journal_entry_id=opening.id if opening else None,
            document_number=opening.document_number if opening else None,
            committed_at=opening.posted_at if opening else None,
            can_reset=can_reset,
        )

    async def preview(
        self, tenant_id: UUID, payload: OpeningBalancePayload
    ) -> OpeningBalancePreviewResponse:
        built = await self._build_lines(tenant_id, payload)
        return built.preview

    async def commit(
        self,
        tenant_id: UUID,
        payload: OpeningBalancePayload,
        *,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> OpeningBalanceStateResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return OpeningBalanceStateResponse.model_validate(replay)
            existing = await self.journals.get_posted_for_source(
                tenant_id, SOURCE_OPENING_BALANCE, tenant_id
            )
            if existing is not None:
                state = await self.get_state(tenant_id)
                await self.idempotency.store(
                    tenant_id, idempotency_key, state.model_dump(mode="json")
                )
                return state
            built = await self._build_lines(tenant_id, payload)
            currency_id = (await self.currencies.get_base(tenant_id)).id
            journal = await self.posting.post_for_document(
                tenant_id,
                source_type=SOURCE_OPENING_BALANCE,
                source_id=tenant_id,
                entry_date=built.entry_date,
                lines=built.journal_lines,
                currency_id=currency_id,
                exchange_rate=Decimal("1"),
                narration="Opening balances",
                branch_id=None,
                actor_id=actor_user_id,
                journal_type=JournalType.OPENING_BALANCE,
            )
            inventory_posted = _ZERO
            for stock_line in payload.stock_lines:
                locked = await self.stock.lock_balance(
                    tenant_id,
                    warehouse_id=stock_line.warehouse_id,
                    product_id=stock_line.product_id,
                    document_date=built.entry_date,
                    can_override_soft_lock=self._can_override,
                )
                result = await self.stock.apply_locked(
                    tenant_id,
                    locked,
                    qty=quantize_quantity(stock_line.quantity),
                    movement_type=StockMovementType.OPENING_STOCK,
                    source_type=SOURCE_OPENING_BALANCE,
                    source_id=journal.id,
                    source_line_id=uuid4(),
                    document_date=built.entry_date,
                    notes="Opening stock",
                    unit_cost=stock_line.unit_cost,
                )
                if result.movement.value is not None:
                    inventory_posted += result.movement.value
            inventory_posted = quantize_money(inventory_posted)
            if inventory_posted != built.inventory_value:
                raise OpeningStockValueMismatchError(
                    details={
                        "inventory_gl": str(built.inventory_value),
                        "layer_value": str(inventory_posted),
                    }
                )
            tenant = await self._require_tenant(tenant_id)
            tenant.books_start_date = payload.books_start_date
            tenant.hard_lock_date = built.entry_date
            tenant.hard_lock_reason = "Opening balances committed"
            await self.session.flush()
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.POST,
                module=ERP_MODULE,
                entity_type="opening_balance",
                entity_id=journal.id,
                new_values={
                    "books_start_date": payload.books_start_date.isoformat(),
                    "journal_entry_id": str(journal.id),
                },
            )
            state = await self.get_state(tenant_id)
            await self.idempotency.store(
                tenant_id, idempotency_key, state.model_dump(mode="json")
            )
            return state

    async def reset(self, tenant_id: UUID, *, actor_user_id: UUID) -> OpeningBalanceStateResponse:
        async with transaction(self.session):
            tenant = await self._require_tenant(tenant_id)
            opening = await self.journals.get_posted_for_source(
                tenant_id, SOURCE_OPENING_BALANCE, tenant_id
            )
            if opening is None:
                raise ValidationError("Opening balances have not been committed")
            if await self._has_activity_after_golive(tenant_id, opening.id):
                raise ValidationError(
                    "Opening balances cannot be reset after other documents have been posted"
                )
            reversal_date = tenant.books_start_date or opening.entry_date
            from app.inventory_management.stock.models import StockMovement

            movements = (
                (
                    await self.session.execute(
                        select(StockMovement).where(
                            StockMovement.tenant_id == tenant_id,
                            StockMovement.source_type == SOURCE_OPENING_BALANCE,
                            StockMovement.source_id == opening.id,
                            StockMovement.movement_type == StockMovementType.OPENING_STOCK.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for movement in movements:
                locked = await self.stock.lock_balance(
                    tenant_id,
                    warehouse_id=movement.warehouse_id,
                    product_id=movement.product_id,
                    document_date=reversal_date,
                    can_override_soft_lock=True,
                    assert_period=False,
                )
                await self.stock.reverse_inbound_locked(
                    tenant_id,
                    locked,
                    qty=abs(movement.qty),
                    movement_type=StockMovementType.ADJUSTMENT_OUT,
                    source_type=SOURCE_OPENING_BALANCE,
                    source_id=opening.id,
                    source_line_id=movement.source_line_id,
                    document_date=reversal_date,
                    notes="Opening balance reset",
                    unit_id=movement.unit_id,
                )
            reversal = await self.posting.reverse(
                tenant_id,
                opening.id,
                reversal_date=reversal_date,
                reason="Opening balance reset",
                actor_id=actor_user_id,
            )
            await self.journals.soft_delete(tenant_id, opening.id)
            await self.journals.soft_delete(tenant_id, reversal.id)
            tenant.books_start_date = None
            tenant.hard_lock_date = None
            tenant.hard_lock_reason = None
            await self.session.flush()
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ERP_MODULE,
                entity_type="opening_balance",
                entity_id=opening.id,
                old_values={"journal_entry_id": str(opening.id)},
            )
            return await self.get_state(tenant_id)

    async def _build_lines(
        self, tenant_id: UUID, payload: OpeningBalancePayload
    ) -> _BuiltOpening:
        if not (
            payload.gl_lines or payload.ar_items or payload.ap_items or payload.stock_lines
        ):
            raise ValidationError("Opening balances require at least one line")
        equity = await self.accounts.resolver.require(
            tenant_id, AccountSystemRole.OPENING_BALANCE_EQUITY
        )
        ar = await self.accounts.resolver.require(
            tenant_id, AccountSystemRole.ACCOUNTS_RECEIVABLE
        )
        ap = await self.accounts.resolver.require(tenant_id, AccountSystemRole.ACCOUNTS_PAYABLE)
        inventory = await self.accounts.resolver.require(tenant_id, AccountSystemRole.INVENTORY)
        entry_date = payload.books_start_date - timedelta(days=1)
        preview_lines: list[OpeningBalancePreviewLine] = []
        journal_lines: list[JournalLineInput] = []
        inventory_value = _ZERO

        def add_line(
            account_id: UUID,
            *,
            debit: Decimal = _ZERO,
            credit: Decimal = _ZERO,
            party_type: PartyType | None = None,
            party_id: UUID | None = None,
            due_date: date | None = None,
            external_reference: str | None = None,
            description: str | None = None,
        ) -> None:
            debit = quantize_money(debit)
            credit = quantize_money(credit)
            if debit == _ZERO and credit == _ZERO:
                return
            journal_lines.append(
                JournalLineInput(
                    account_id=account_id,
                    debit=debit,
                    credit=credit,
                    party_type=party_type,
                    party_id=party_id,
                    due_date=due_date,
                    external_reference=external_reference,
                    description=description,
                )
            )
            preview_lines.append(
                OpeningBalancePreviewLine(
                    account_id=account_id,
                    account_code="",
                    account_name="",
                    debit=debit,
                    credit=credit,
                    party_id=party_id,
                    due_date=due_date,
                    external_reference=external_reference,
                    description=description,
                )
            )

        for line in payload.gl_lines:
            add_line(
                line.account_id,
                debit=line.debit,
                credit=line.credit,
                description=line.description,
            )
        for item in payload.ar_items:
            add_line(
                ar.id,
                debit=item.amount,
                party_type=PartyType.CUSTOMER,
                party_id=item.party_id,
                due_date=item.due_date,
                external_reference=item.external_reference,
                description=item.description,
            )
        for item in payload.ap_items:
            add_line(
                ap.id,
                credit=item.amount,
                party_type=PartyType.SUPPLIER,
                party_id=item.party_id,
                due_date=item.due_date,
                external_reference=item.external_reference,
                description=item.description,
            )
        for stock in payload.stock_lines:
            inventory_value += quantize_money(stock.quantity * stock.unit_cost)
        inventory_value = quantize_money(inventory_value)
        if inventory_value > _ZERO:
            add_line(inventory.id, debit=inventory_value, description="Opening inventory")
        total_debit = quantize_money(sum((item.debit for item in journal_lines), _ZERO))
        total_credit = quantize_money(sum((item.credit for item in journal_lines), _ZERO))
        difference = quantize_money(total_debit - total_credit)
        if difference > _ZERO:
            add_line(equity.id, credit=difference, description="Opening balance equity")
            total_credit = quantize_money(total_credit + difference)
        elif difference < _ZERO:
            add_line(equity.id, debit=-difference, description="Opening balance equity")
            total_debit = quantize_money(total_debit + (-difference))
            difference = -difference
        else:
            difference = _ZERO
        by_id = {row.id: row for row in await self.accounts.repo.list_all(tenant_id)}
        filled: list[OpeningBalancePreviewLine] = []
        for preview in preview_lines:
            account = by_id.get(preview.account_id)
            filled.append(
                preview.model_copy(
                    update={
                        "account_code": account.code if account else "",
                        "account_name": account.name if account else "",
                    }
                )
            )
        preview = OpeningBalancePreviewResponse(
            books_start_date=payload.books_start_date,
            entry_date=entry_date,
            opening_balance_equity_account_id=equity.id,
            difference=difference,
            total_debit=total_debit,
            total_credit=total_credit,
            inventory_value=inventory_value,
            lines=filled,
        )
        return _BuiltOpening(
            preview=preview,
            journal_lines=journal_lines,
            entry_date=entry_date,
            inventory_value=inventory_value,
        )

    async def _has_activity_after_golive(self, tenant_id: UUID, opening_id: UUID) -> bool:
        statement = (
            select(func.count())
            .select_from(JournalEntry)
            .where(
                JournalEntry.tenant_id == tenant_id,
                JournalEntry.deleted_at.is_(None),
                JournalEntry.status == JournalEntryStatus.POSTED.value,
                JournalEntry.id != opening_id,
                JournalEntry.journal_type != JournalType.REVERSAL.value,
            )
        )
        return int(await self.session.scalar(statement) or 0) > 0

    async def _require_tenant(self, tenant_id: UUID) -> Tenant:
        tenant = await self.session.get(Tenant, tenant_id)
        if tenant is None:
            raise ResourceNotFoundError("Tenant not found")
        return tenant


class _BuiltOpening:
    def __init__(
        self,
        *,
        preview: OpeningBalancePreviewResponse,
        journal_lines: list[JournalLineInput],
        entry_date: date,
        inventory_value: Decimal,
    ) -> None:
        self.preview = preview
        self.journal_lines = journal_lines
        self.entry_date = entry_date
        self.inventory_value = inventory_value

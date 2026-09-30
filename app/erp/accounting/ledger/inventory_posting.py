"""Inventory documents post to the GL only through LedgerPostingService."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.org_service import OrganizationService
from app.common.utils.currency import quantize_money
from app.core.enums import AccountSystemRole, JournalType
from app.core.exceptions import ValidationError
from app.erp.accounting.accounts.service import AccountResolver
from app.erp.accounting.ledger.models import JournalEntry
from app.erp.accounting.ledger.posting import LedgerPostingService
from app.erp.accounting.ledger.schemas import JournalLineInput
from app.erp.exchange_rates.service import CurrencyService

_ZERO = Decimal("0")
SOURCE_GOODS_RECEIPT = "goods_receipt"
SOURCE_DELIVERY_NOTE = "delivery_note"
SOURCE_SALES_RETURN = "sales_return"
SOURCE_PURCHASE_RETURN = "purchase_return"
SOURCE_QUALITY_INSPECTION = "quality_inspection"
SOURCE_STOCK_ADJUSTMENT = "stock_adjustment"
SOURCE_GOODS_RECEIPT_CHARGE_ADJUSTMENT = "goods_receipt_charge_adjustment"


class InventoryLedgerService:
    """Build inventory journals and hand them to LedgerPostingService.

    Stock transfers are GL-neutral: one inventory account per tenant, so a
    warehouse-to-warehouse move does not write a journal.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.posting = LedgerPostingService(session, actor_permissions=actor_permissions)
        self.resolver = AccountResolver(session)
        self.currencies = CurrencyService(session)
        self.org = OrganizationService(session)

    async def post_goods_receipt(
        self,
        tenant_id: UUID,
        *,
        source_id: UUID,
        entry_date: date,
        amount: Decimal,
        actor_id: UUID,
        branch_id: UUID | None = None,
        document_number: str | None = None,
    ) -> None:
        await self.post_goods_receipt_with_charges(
            tenant_id,
            source_id=source_id,
            entry_date=entry_date,
            goods_amount=amount,
            charge_credits={},
            actor_id=actor_id,
            branch_id=branch_id,
            document_number=document_number,
        )

    async def post_goods_receipt_with_charges(
        self,
        tenant_id: UUID,
        *,
        source_id: UUID,
        entry_date: date,
        goods_amount: Decimal,
        charge_credits: dict[UUID, Decimal],
        actor_id: UUID,
        branch_id: UUID | None = None,
        document_number: str | None = None,
    ) -> None:
        goods = quantize_money(goods_amount)
        charges_total = quantize_money(sum(charge_credits.values(), _ZERO))
        inventory_total = quantize_money(goods + charges_total)
        if inventory_total == _ZERO and not charge_credits:
            return
        if inventory_total == _ZERO and charge_credits:
            raise ValidationError("Goods receipt inventory amount cannot be zero with charges")
        if not charge_credits:
            await self._post_pair(
                tenant_id,
                source_type=SOURCE_GOODS_RECEIPT,
                source_id=source_id,
                entry_date=entry_date,
                debit_role=AccountSystemRole.INVENTORY,
                credit_role=AccountSystemRole.GOODS_RECEIVED_NOT_INVOICED,
                amount=goods,
                narration=f"Goods receipt {document_number or source_id}",
                actor_id=actor_id,
                branch_id=branch_id,
            )
            return
        await self._ensure_can_post(tenant_id, entry_date)
        inventory = await self.resolver.require(tenant_id, AccountSystemRole.INVENTORY)
        grni = await self.resolver.require(tenant_id, AccountSystemRole.GOODS_RECEIVED_NOT_INVOICED)
        lines: list[JournalLineInput] = [
            JournalLineInput(
                account_id=inventory.id,
                debit=inventory_total,
                credit=_ZERO,
                description="Goods receipt",
            )
        ]
        if goods > _ZERO:
            lines.append(
                JournalLineInput(
                    account_id=grni.id,
                    debit=_ZERO,
                    credit=goods,
                    description="Goods received not invoiced",
                )
            )
        for account_id, amount in charge_credits.items():
            credit_amount = quantize_money(amount)
            if credit_amount <= _ZERO:
                continue
            lines.append(
                JournalLineInput(
                    account_id=account_id,
                    debit=_ZERO,
                    credit=credit_amount,
                    description="Import charge",
                )
            )
        await self._commit_lines(
            tenant_id,
            source_type=SOURCE_GOODS_RECEIPT,
            source_id=source_id,
            entry_date=entry_date,
            lines=lines,
            narration=f"Goods receipt {document_number or source_id}",
            actor_id=actor_id,
            branch_id=branch_id,
        )

    async def post_grn_charge_adjustment(
        self,
        tenant_id: UUID,
        *,
        source_id: UUID,
        entry_date: date,
        charge_credits: dict[UUID, Decimal],
        actor_id: UUID,
        branch_id: UUID | None = None,
        document_number: str | None = None,
    ) -> None:
        inventory_delta = quantize_money(sum(charge_credits.values(), _ZERO))
        if inventory_delta == _ZERO:
            return
        await self._ensure_can_post(tenant_id, entry_date)
        inventory = await self.resolver.require(tenant_id, AccountSystemRole.INVENTORY)
        lines: list[JournalLineInput] = []
        if inventory_delta > _ZERO:
            lines.append(
                JournalLineInput(
                    account_id=inventory.id,
                    debit=inventory_delta,
                    credit=_ZERO,
                    description="GRN charge adjustment",
                )
            )
        else:
            lines.append(
                JournalLineInput(
                    account_id=inventory.id,
                    debit=_ZERO,
                    credit=-inventory_delta,
                    description="GRN charge adjustment",
                )
            )
        for account_id, amount in charge_credits.items():
            credit_amount = quantize_money(amount)
            if credit_amount == _ZERO:
                continue
            if credit_amount > _ZERO:
                lines.append(
                    JournalLineInput(
                        account_id=account_id,
                        debit=_ZERO,
                        credit=credit_amount,
                        description="Import charge adjustment",
                    )
                )
            else:
                lines.append(
                    JournalLineInput(
                        account_id=account_id,
                        debit=-credit_amount,
                        credit=_ZERO,
                        description="Import charge adjustment",
                    )
                )
        await self._commit_lines(
            tenant_id,
            source_type=SOURCE_GOODS_RECEIPT_CHARGE_ADJUSTMENT,
            source_id=source_id,
            entry_date=entry_date,
            lines=lines,
            narration=f"GRN charge adjustment {document_number or source_id}",
            actor_id=actor_id,
            branch_id=branch_id,
        )

    async def post_delivery_note(
        self,
        tenant_id: UUID,
        *,
        source_id: UUID,
        entry_date: date,
        amount: Decimal,
        actor_id: UUID,
        branch_id: UUID | None = None,
        document_number: str | None = None,
    ) -> None:
        await self._post_pair(
            tenant_id,
            source_type=SOURCE_DELIVERY_NOTE,
            source_id=source_id,
            entry_date=entry_date,
            debit_role=AccountSystemRole.COGS,
            credit_role=AccountSystemRole.INVENTORY,
            amount=amount,
            narration=f"Delivery note {document_number or source_id}",
            actor_id=actor_id,
            branch_id=branch_id,
        )

    async def post_sales_return(
        self,
        tenant_id: UUID,
        *,
        source_id: UUID,
        entry_date: date,
        restored_amount: Decimal,
        scrap_amount: Decimal,
        actor_id: UUID,
        branch_id: UUID | None = None,
        document_number: str | None = None,
    ) -> None:
        await self._ensure_can_post(tenant_id, entry_date)
        restored = quantize_money(abs(restored_amount))
        scrap = quantize_money(abs(scrap_amount))
        lines: list[JournalLineInput] = []
        if restored > _ZERO:
            inventory = await self.resolver.require(tenant_id, AccountSystemRole.INVENTORY)
            cogs = await self.resolver.require(tenant_id, AccountSystemRole.COGS)
            lines.extend(
                self._balanced_pair(
                    debit_account_id=inventory.id,
                    credit_account_id=cogs.id,
                    amount=restored,
                    description="Sales return restock",
                )
            )
        if scrap > _ZERO:
            scrap_account = await self.resolver.require(tenant_id, AccountSystemRole.STOCK_SCRAP)
            inventory = await self.resolver.require(tenant_id, AccountSystemRole.INVENTORY)
            lines.extend(
                self._balanced_pair(
                    debit_account_id=scrap_account.id,
                    credit_account_id=inventory.id,
                    amount=scrap,
                    description="Sales return scrap",
                )
            )
        await self._commit_lines(
            tenant_id,
            source_type=SOURCE_SALES_RETURN,
            source_id=source_id,
            entry_date=entry_date,
            lines=lines,
            narration=f"Sales return {document_number or source_id}",
            actor_id=actor_id,
            branch_id=branch_id,
        )

    async def post_purchase_return(
        self,
        tenant_id: UUID,
        *,
        source_id: UUID,
        entry_date: date,
        amount: Decimal,
        actor_id: UUID,
        branch_id: UUID | None = None,
        document_number: str | None = None,
    ) -> None:
        await self._post_pair(
            tenant_id,
            source_type=SOURCE_PURCHASE_RETURN,
            source_id=source_id,
            entry_date=entry_date,
            debit_role=AccountSystemRole.GOODS_RECEIVED_NOT_INVOICED,
            credit_role=AccountSystemRole.INVENTORY,
            amount=amount,
            narration=f"Purchase return {document_number or source_id}",
            actor_id=actor_id,
            branch_id=branch_id,
        )

    async def post_quality_scrap(
        self,
        tenant_id: UUID,
        *,
        source_id: UUID,
        entry_date: date,
        amount: Decimal,
        actor_id: UUID,
        branch_id: UUID | None = None,
        document_number: str | None = None,
    ) -> None:
        await self._post_pair(
            tenant_id,
            source_type=SOURCE_QUALITY_INSPECTION,
            source_id=source_id,
            entry_date=entry_date,
            debit_role=AccountSystemRole.STOCK_SCRAP,
            credit_role=AccountSystemRole.INVENTORY,
            amount=amount,
            narration=f"Quality inspection scrap {document_number or source_id}",
            actor_id=actor_id,
            branch_id=branch_id,
        )

    async def post_stock_adjustment(
        self,
        tenant_id: UUID,
        *,
        source_id: UUID,
        entry_date: date,
        inventory_delta: Decimal,
        actor_id: UUID,
        branch_id: UUID | None = None,
        document_number: str | None = None,
    ) -> None:
        delta = quantize_money(inventory_delta)
        if delta == _ZERO:
            return
        if delta > _ZERO:
            debit, credit = AccountSystemRole.INVENTORY, AccountSystemRole.INVENTORY_ADJUSTMENT
            amount = delta
        else:
            debit, credit = AccountSystemRole.INVENTORY_ADJUSTMENT, AccountSystemRole.INVENTORY
            amount = -delta
        await self._post_pair(
            tenant_id,
            source_type=SOURCE_STOCK_ADJUSTMENT,
            source_id=source_id,
            entry_date=entry_date,
            debit_role=debit,
            credit_role=credit,
            amount=amount,
            narration=f"Stock adjustment {document_number or source_id}",
            actor_id=actor_id,
            branch_id=branch_id,
        )

    async def post_stock_adjustment_damage(
        self,
        tenant_id: UUID,
        *,
        source_id: UUID,
        entry_date: date,
        scrap_amount: Decimal,
        actor_id: UUID,
        branch_id: UUID | None = None,
        document_number: str | None = None,
    ) -> None:
        amount = quantize_money(scrap_amount)
        if amount == _ZERO:
            return
        await self._post_pair(
            tenant_id,
            source_type=SOURCE_STOCK_ADJUSTMENT,
            source_id=source_id,
            entry_date=entry_date,
            debit_role=AccountSystemRole.STOCK_SCRAP,
            credit_role=AccountSystemRole.INVENTORY,
            amount=amount,
            narration=f"Stock adjustment damage {document_number or source_id}",
            actor_id=actor_id,
            branch_id=branch_id,
        )

    async def reverse(
        self,
        tenant_id: UUID,
        *,
        source_type: str,
        source_id: UUID,
        reversal_date: date,
        reason: str,
        actor_id: UUID,
    ) -> JournalEntry | None:
        existing = await self.posting.repo.get_posted_for_source(tenant_id, source_type, source_id)
        if existing is None:
            return None
        return await self.posting.reverse(
            tenant_id,
            existing.id,
            reversal_date=reversal_date,
            reason=reason,
            actor_id=actor_id,
        )

    async def _ensure_can_post(self, tenant_id: UUID, entry_date: date) -> None:
        tenant = await self.org._require_tenant(tenant_id)
        if tenant.books_start_date is not None and entry_date < tenant.books_start_date:
            raise ValidationError(
                "Inventory journal entry date is before the tenant books start date"
            )

    async def _post_pair(
        self,
        tenant_id: UUID,
        *,
        source_type: str,
        source_id: UUID,
        entry_date: date,
        debit_role: AccountSystemRole,
        credit_role: AccountSystemRole,
        amount: Decimal,
        narration: str,
        actor_id: UUID,
        branch_id: UUID | None,
    ) -> None:
        await self._ensure_can_post(tenant_id, entry_date)
        money = quantize_money(abs(amount))
        if money == _ZERO:
            return
        debit = await self.resolver.require(tenant_id, debit_role)
        credit = await self.resolver.require(tenant_id, credit_role)
        await self._commit_lines(
            tenant_id,
            source_type=source_type,
            source_id=source_id,
            entry_date=entry_date,
            lines=self._balanced_pair(
                debit_account_id=debit.id,
                credit_account_id=credit.id,
                amount=money,
            ),
            narration=narration,
            actor_id=actor_id,
            branch_id=branch_id,
        )

    async def _commit_lines(
        self,
        tenant_id: UUID,
        *,
        source_type: str,
        source_id: UUID,
        entry_date: date,
        lines: list[JournalLineInput],
        narration: str,
        actor_id: UUID,
        branch_id: UUID | None,
    ) -> None:
        if not lines:
            return
        currency_id = (await self.currencies.get_base(tenant_id)).id
        await self.posting.post_for_document(
            tenant_id,
            source_type=source_type,
            source_id=source_id,
            entry_date=entry_date,
            lines=lines,
            currency_id=currency_id,
            exchange_rate=Decimal("1"),
            narration=narration,
            branch_id=branch_id,
            actor_id=actor_id,
            journal_type=JournalType.SYSTEM,
        )

    @staticmethod
    def _balanced_pair(
        *,
        debit_account_id: UUID,
        credit_account_id: UUID,
        amount: Decimal,
        description: str | None = None,
    ) -> list[JournalLineInput]:
        return [
            JournalLineInput(
                account_id=debit_account_id, debit=amount, credit=_ZERO, description=description
            ),
            JournalLineInput(
                account_id=credit_account_id, debit=_ZERO, credit=amount, description=description
            ),
        ]

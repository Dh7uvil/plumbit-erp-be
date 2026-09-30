"""Bank account use cases."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import ACCOUNTING_MODULE
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.currency import quantize_money
from app.core.enums import AccountSubtype, AuditAction, ChequeDirection, ChequeStatus
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError, ValidationError
from app.db.session import transaction
from app.erp.accounting.accounts.service import AccountService
from app.erp.accounting.bank_accounts.models import BankAccount
from app.erp.accounting.bank_accounts.repository import BankAccountRepository
from app.erp.accounting.bank_accounts.schemas import (
    BankAccountCreate,
    BankAccountResponse,
    BankAccountUpdate,
    BankBalanceProjectionLine,
    BankBalanceProjectionResponse,
)
from app.erp.exchange_rates.service import CurrencyService


def _snapshot(row: BankAccount) -> dict[str, object]:
    return {
        "account_id": str(row.account_id),
        "account_name": row.account_name,
        "bank_name": row.bank_name,
        "branch_name": row.branch_name,
        "account_number": row.account_number,
        "iban": row.iban,
        "swift": row.swift,
        "currency_id": str(row.currency_id),
        "opening_balance": str(row.opening_balance),
        "opening_date": row.opening_date.isoformat() if row.opening_date else None,
        "is_default": row.is_default,
        "is_active": row.is_active,
    }


class BankAccountService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = BankAccountRepository(session)
        self.accounts = AccountService(session)
        self.currencies = CurrencyService(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        is_active: bool | None = None,
        currency_id: UUID | None = None,
    ) -> tuple[list[BankAccountResponse], int]:
        filters: dict[str, object] = {}
        if is_active is not None:
            filters["is_active"] = is_active
        if currency_id is not None:
            filters["currency_id"] = currency_id
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        return [BankAccountResponse.model_validate(row) for row in rows], total

    async def get(self, tenant_id: UUID, bank_account_id: UUID) -> BankAccountResponse:
        return BankAccountResponse.model_validate(await self._require(tenant_id, bank_account_id))

    async def require(self, tenant_id: UUID, bank_account_id: UUID) -> BankAccount:
        return await self._require(tenant_id, bank_account_id)

    async def create(
        self, tenant_id: UUID, payload: BankAccountCreate, *, actor_user_id: UUID
    ) -> BankAccountResponse:
        await self._validate_account(tenant_id, payload.account_id)
        await self.currencies.require_id(tenant_id, payload.currency_id)
        async with transaction(self.session):
            if payload.is_default:
                await self._clear_default(tenant_id)
            try:
                row = await self.repo.create(
                    tenant_id,
                    {
                        **payload.model_dump(),
                        "created_by": actor_user_id,
                        "updated_by": actor_user_id,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "This chart account is already linked to a bank account"
                ) from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ACCOUNTING_MODULE,
                entity_type="bank_account",
                entity_id=row.id,
                new_values=_snapshot(row),
            )
            return BankAccountResponse.model_validate(row)

    async def update(
        self,
        tenant_id: UUID,
        bank_account_id: UUID,
        payload: BankAccountUpdate,
        *,
        actor_user_id: UUID,
    ) -> BankAccountResponse:
        values = payload.model_dump(exclude_unset=True)
        if "currency_id" in values and values["currency_id"] is not None:
            await self.currencies.require_id(tenant_id, values["currency_id"])
        async with transaction(self.session):
            row = await self._require(tenant_id, bank_account_id)
            old_values = _snapshot(row)
            if values.get("is_default"):
                await self._clear_default(tenant_id, exclude_id=bank_account_id)
            updated = await self.repo.update(
                tenant_id,
                bank_account_id,
                {**values, "updated_by": actor_user_id},
            )
            if updated is None:
                raise ResourceNotFoundError("Bank account not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ACCOUNTING_MODULE,
                entity_type="bank_account",
                entity_id=bank_account_id,
                old_values=old_values,
                new_values=_snapshot(updated),
            )
            return BankAccountResponse.model_validate(updated)

    async def delete(
        self, tenant_id: UUID, bank_account_id: UUID, *, actor_user_id: UUID
    ) -> BankAccountResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, bank_account_id)
            old_values = _snapshot(row)
            deleted = await self.repo.soft_delete(tenant_id, bank_account_id)
            if deleted is None:
                raise ResourceNotFoundError("Bank account not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ACCOUNTING_MODULE,
                entity_type="bank_account",
                entity_id=bank_account_id,
                old_values=old_values,
            )
            return BankAccountResponse.model_validate(deleted)

    async def balance_projection(
        self,
        tenant_id: UUID,
        bank_account_id: UUID,
        *,
        as_of: date | None = None,
        horizon_days: int = 30,
    ) -> BankBalanceProjectionResponse:
        from app.erp.accounting.cheques.models import Cheque

        row = await self._require(tenant_id, bank_account_id)
        as_of_date = as_of or date.today()
        horizon_date = as_of_date + timedelta(days=max(horizon_days, 1))
        balance = await self.accounts.get_balance(tenant_id, row.account_id, as_of=as_of_date)
        book_balance = balance.signed_balance
        currency = await self.currencies.get(tenant_id, row.currency_id)

        due_or_cheque = func.coalesce(Cheque.due_date, Cheque.cheque_date)
        cheque_rows = (
            await self.session.execute(
                select(Cheque).where(
                    Cheque.tenant_id == tenant_id,
                    Cheque.deleted_at.is_(None),
                    Cheque.bank_account_id == bank_account_id,
                    Cheque.status.in_(
                        (ChequeStatus.ISSUED.value, ChequeStatus.DEPOSITED.value)
                    ),
                    due_or_cheque > as_of_date,
                    due_or_cheque <= horizon_date,
                ).order_by(due_or_cheque.asc())
            )
        ).scalars().all()

        lines: list[BankBalanceProjectionLine] = [
            BankBalanceProjectionLine(
                kind="book",
                event_date=as_of_date,
                description="Book balance as of date",
                amount=book_balance,
            )
        ]
        projected = book_balance
        for cheque in cheque_rows:
            if cheque.direction == ChequeDirection.INBOUND.value:
                impact = cheque.amount
                kind = "pdc_inbound"
                description = f"Inbound PDC {cheque.cheque_number}"
            else:
                impact = quantize_money(Decimal("0") - cheque.amount)
                kind = "pdc_outbound"
                description = f"Outbound PDC {cheque.cheque_number}"
            projected = quantize_money(projected + impact)
            lines.append(
                BankBalanceProjectionLine(
                    kind=kind,
                    event_date=cheque.due_date or cheque.cheque_date,
                    description=description,
                    amount=impact,
                )
            )
        return BankBalanceProjectionResponse(
            bank_account_id=row.id,
            account_id=row.account_id,
            currency_code=currency.code,
            as_of=as_of_date,
            horizon_date=horizon_date,
            book_balance=book_balance,
            projected_balance=projected,
            lines=lines,
        )

    async def _require(self, tenant_id: UUID, bank_account_id: UUID) -> BankAccount:
        row = await self.repo.get(tenant_id, bank_account_id)
        if row is None:
            raise ResourceNotFoundError("Bank account not found")
        return row

    async def _validate_account(self, tenant_id: UUID, account_id: UUID) -> None:
        account = await self.accounts.require_postable(tenant_id, account_id)
        if account.account_subtype != AccountSubtype.BANK.value:
            raise ValidationError("Bank account must link to a BANK chart account")

    async def _clear_default(self, tenant_id: UUID, *, exclude_id: UUID | None = None) -> None:
        rows, _ = await self.repo.list(tenant_id, page=PageParams(page=1, page_size=500))
        for row in rows:
            if row.is_default and row.id != exclude_id:
                await self.repo.update(tenant_id, row.id, {"is_default": False})

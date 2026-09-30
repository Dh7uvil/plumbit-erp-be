"""Chart of accounts use cases and system-role resolver."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import ACCOUNTING_MODULE
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.core.enums import AccountSubtype, AccountSystemRole, AccountType, AuditAction
from app.core.exceptions import (
    AccountNotPostableError,
    AccountRoleUnmappedError,
    DuplicateResourceError,
    ResourceNotFoundError,
    ValidationError,
)
from app.db.session import transaction
from app.erp.accounting.accounts.models import Account
from app.erp.accounting.accounts.repository import AccountRepository
from app.erp.accounting.accounts.schemas import (
    AccountBalanceResponse,
    AccountCreate,
    AccountPeriodBalance,
    AccountPeriodBalancesResponse,
    AccountResponse,
    AccountTreeNode,
    AccountUpdate,
    SystemRoleMapping,
)
from app.erp.accounting.fiscal import FiscalYearConfig
from app.erp.exchange_rates.service import CurrencyService

_CONTROL_SUBTYPES = frozenset(
    {AccountSubtype.ACCOUNTS_RECEIVABLE.value, AccountSubtype.ACCOUNTS_PAYABLE.value}
)
_SUBTYPES_BY_TYPE: dict[str, frozenset[str]] = {
    AccountType.ASSET.value: frozenset(
        {
            AccountSubtype.BANK.value,
            AccountSubtype.CASH.value,
            AccountSubtype.ACCOUNTS_RECEIVABLE.value,
            AccountSubtype.STOCK.value,
            AccountSubtype.FIXED_ASSET.value,
            AccountSubtype.OTHER_CURRENT_ASSET.value,
            AccountSubtype.TAX_RECEIVABLE.value,
        }
    ),
    AccountType.LIABILITY.value: frozenset(
        {
            AccountSubtype.ACCOUNTS_PAYABLE.value,
            AccountSubtype.OTHER_CURRENT_LIABILITY.value,
            AccountSubtype.TAX_PAYABLE.value,
        }
    ),
    AccountType.EQUITY.value: frozenset({AccountSubtype.EQUITY.value}),
    AccountType.INCOME.value: frozenset(
        {AccountSubtype.INCOME.value, AccountSubtype.OTHER_INCOME.value}
    ),
    AccountType.EXPENSE.value: frozenset(
        {
            AccountSubtype.COGS.value,
            AccountSubtype.EXPENSE.value,
            AccountSubtype.OTHER_EXPENSE.value,
        }
    ),
}


class AccountResolver:
    """Resolve the account mapped to a system role. Stage G posts against these roles."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AccountRepository(session)

    async def require(self, tenant_id: UUID, role: AccountSystemRole | str) -> Account:
        value = role.value if isinstance(role, AccountSystemRole) else role
        row = await self.repo.get_by_system_role(tenant_id, value)
        if row is None:
            raise AccountRoleUnmappedError(details={"role": value})
        return row


class PartyAccountResolver:
    """Resolve a party's AR/AP control account, then fall back to the system role."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AccountRepository(session)
        self.resolver = AccountResolver(session)

    async def resolve_receivable(self, tenant_id: UUID, customer_id: UUID) -> Account:
        from app.crm.customers.service import CUSTOMER_PARTY_ROLE, CustomerService

        party = await CustomerService(self.session, role=CUSTOMER_PARTY_ROLE).get(
            tenant_id, customer_id
        )
        if party.receivable_account_id is not None:
            return await self._require_control(
                tenant_id, party.receivable_account_id, AccountSubtype.ACCOUNTS_RECEIVABLE
            )
        return await self.resolver.require(tenant_id, AccountSystemRole.ACCOUNTS_RECEIVABLE)

    async def resolve_payable(self, tenant_id: UUID, supplier_id: UUID) -> Account:
        from app.crm.customers.service import SUPPLIER_PARTY_ROLE, CustomerService

        party = await CustomerService(self.session, role=SUPPLIER_PARTY_ROLE).get(
            tenant_id, supplier_id
        )
        if party.payable_account_id is not None:
            return await self._require_control(
                tenant_id, party.payable_account_id, AccountSubtype.ACCOUNTS_PAYABLE
            )
        return await self.resolver.require(tenant_id, AccountSystemRole.ACCOUNTS_PAYABLE)

    async def _require_control(
        self, tenant_id: UUID, account_id: UUID, subtype: AccountSubtype
    ) -> Account:
        row = await self.repo.get(tenant_id, account_id)
        if row is None:
            raise ResourceNotFoundError("Account not found")
        if row.is_group or not row.is_active or row.is_blocked:
            raise AccountNotPostableError(
                details={
                    "account_id": str(account_id),
                    "is_group": row.is_group,
                    "is_blocked": row.is_blocked,
                }
            )
        if row.account_subtype != subtype.value:
            raise ValidationError(
                f"Account must have subtype {subtype.value}",
                details={"account_id": str(account_id), "account_subtype": row.account_subtype},
            )
        return row


class AccountService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AccountRepository(session)
        self.resolver = AccountResolver(session)
        self.party_resolver = PartyAccountResolver(session)
        self.currencies = CurrencyService(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        account_type: str | None = None,
        account_subtype: str | None = None,
        is_group: bool | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[AccountResponse], int]:
        filters: dict[str, object] = {}
        if account_type is not None:
            filters["account_type"] = account_type
        if account_subtype is not None:
            filters["account_subtype"] = account_subtype
        if is_group is not None:
            filters["is_group"] = is_group
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        parent_map = await self._parent_map(tenant_id, rows)
        return [self._to_response(row, parent_map) for row in rows], total

    async def tree(self, tenant_id: UUID) -> list[AccountTreeNode]:
        rows = await self.repo.list_all(tenant_id)
        by_id = {row.id: AccountTreeNode.model_validate(row) for row in rows}
        roots: list[AccountTreeNode] = []
        for row in rows:
            node = by_id[row.id]
            if row.parent_id is not None and row.parent_id in by_id:
                by_id[row.parent_id].children.append(node)
            else:
                roots.append(node)
        return roots

    async def get(self, tenant_id: UUID, account_id: UUID) -> AccountResponse:
        row = await self._require(tenant_id, account_id)
        parent_map = await self._parent_map(tenant_id, [row])
        return self._to_response(
            row,
            parent_map,
            has_children=await self.repo.count_children(tenant_id, account_id) > 0,
            has_journal_lines=await self._has_gl_lines(tenant_id, account_id),
        )

    async def require_postable(self, tenant_id: UUID, account_id: UUID) -> Account:
        row = await self._require(tenant_id, account_id)
        if row.is_group or not row.is_active or row.is_blocked:
            raise AccountNotPostableError(
                details={
                    "account_id": str(account_id),
                    "is_group": row.is_group,
                    "is_blocked": row.is_blocked,
                }
            )
        return row

    async def require_control_account(
        self, tenant_id: UUID, account_id: UUID, *, subtype: AccountSubtype
    ) -> Account:
        row = await self.require_postable(tenant_id, account_id)
        if row.account_subtype != subtype.value:
            raise ValidationError(
                f"Account must have subtype {subtype.value}",
                details={"account_id": str(account_id), "account_subtype": row.account_subtype},
            )
        return row

    async def resolve_income_account(self, tenant_id: UUID, product_id: UUID) -> Account:
        return await self._resolve_product_account(
            tenant_id, product_id, field="income_account_id", role=AccountSystemRole.SALES_REVENUE
        )

    async def resolve_purchase_account(self, tenant_id: UUID, product_id: UUID) -> Account:
        return await self._resolve_product_account(
            tenant_id, product_id, field="purchase_account_id", role=AccountSystemRole.PURCHASES
        )

    async def _resolve_product_account(
        self,
        tenant_id: UUID,
        product_id: UUID,
        *,
        field: str,
        role: AccountSystemRole,
    ) -> Account:
        from app.inventory_management.categories.service import CategoryService
        from app.inventory_management.products.service import ProductService

        product = await ProductService(self.session).get(tenant_id, product_id)
        account_id = getattr(product, field)
        if account_id is not None:
            return await self.require_postable(tenant_id, account_id)
        if product.category_id is not None:
            category = await CategoryService(self.session).get(tenant_id, product.category_id)
            category_account_id = getattr(category, field)
            if category_account_id is not None:
                return await self.require_postable(tenant_id, category_account_id)
        return await self.resolver.require(tenant_id, role)

    def is_control_account(self, row: Account) -> bool:
        return row.account_subtype in _CONTROL_SUBTYPES

    def _assert_subtype_for_type(self, account_type: str, account_subtype: str) -> None:
        allowed = _SUBTYPES_BY_TYPE.get(account_type)
        if allowed is None or account_subtype not in allowed:
            raise ValidationError(
                "Account subtype is not valid for this account type",
                details={"account_type": account_type, "account_subtype": account_subtype},
            )

    async def create(
        self, tenant_id: UUID, payload: AccountCreate, *, actor_user_id: UUID
    ) -> AccountResponse:
        async with transaction(self.session):
            self._assert_subtype_for_type(
                payload.account_type.value, payload.account_subtype.value
            )
            depth = await self._validate_parent(
                tenant_id, payload.parent_id, payload.account_type.value
            )
            if payload.currency_id is not None:
                await self.currencies.require_id(tenant_id, payload.currency_id)
            try:
                row = await self.repo.create(
                    tenant_id,
                    {
                        "code": payload.code,
                        "name": payload.name,
                        "description": payload.description,
                        "account_type": payload.account_type.value,
                        "account_subtype": payload.account_subtype.value,
                        "parent_id": payload.parent_id,
                        "depth": depth,
                        "is_group": payload.is_group,
                        "is_blocked": payload.is_blocked,
                        "is_system": False,
                        "currency_id": payload.currency_id,
                        "created_by": actor_user_id,
                        "updated_by": actor_user_id,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError("An account with this code already exists") from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ACCOUNTING_MODULE,
                entity_type="account",
                entity_id=row.id,
                new_values=_account_snapshot(row),
            )
            parent_map = await self._parent_map(tenant_id, [row])
            return self._to_response(row, parent_map)

    async def update(
        self,
        tenant_id: UUID,
        account_id: UUID,
        payload: AccountUpdate,
        *,
        actor_user_id: UUID,
    ) -> AccountResponse:
        values = payload.model_dump(exclude_unset=True)
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            existing = await self._require(tenant_id, account_id)
            old_values = _account_snapshot(existing)
            if "code" in values and values["code"] != existing.code and existing.is_system:
                raise ValidationError("System account codes cannot be changed")
            if "account_type" in values and values["account_type"] is not None:
                requested = (
                    values["account_type"].value
                    if isinstance(values["account_type"], AccountType)
                    else str(values["account_type"])
                )
                if requested != existing.account_type and await self._has_gl_lines(
                    tenant_id, account_id
                ):
                    raise ValidationError("Account type cannot change once journal lines exist")
                values["account_type"] = requested
            if "account_subtype" in values and values["account_subtype"] is not None:
                subtype = values["account_subtype"]
                requested_subtype = (
                    subtype.value if isinstance(subtype, AccountSubtype) else str(subtype)
                )
                if (
                    requested_subtype != existing.account_subtype
                    and await self._has_gl_lines(tenant_id, account_id)
                ):
                    raise ValidationError(
                        "Account subtype cannot change once journal lines exist"
                    )
                values["account_subtype"] = requested_subtype
            parent_id = values.get("parent_id", existing.parent_id)
            account_type = values.get("account_type", existing.account_type)
            account_subtype = values.get("account_subtype", existing.account_subtype)
            self._assert_subtype_for_type(str(account_type), str(account_subtype))
            if "is_group" in values and values["is_group"] is not None:
                next_is_group = bool(values["is_group"])
                if next_is_group and not existing.is_group:
                    if await self._has_gl_lines(tenant_id, account_id):
                        raise ValidationError(
                            "Cannot convert an account with journal lines into a group"
                        )
                    if await self.repo.count_children(tenant_id, account_id) > 0:
                        raise ValidationError(
                            "Cannot convert an account with children into a group"
                        )
                if not next_is_group and existing.is_group:
                    if await self.repo.count_children(tenant_id, account_id) > 0:
                        raise ValidationError(
                            "Cannot convert a group with children into a postable account"
                        )
            if "parent_id" in values or "account_type" in values:
                if parent_id == account_id:
                    raise ValidationError("An account cannot be its own parent")
                values["depth"] = await self._validate_parent(
                    tenant_id, parent_id, str(account_type), exclude_id=account_id
                )
            if values.get("currency_id") is not None:
                await self.currencies.require_id(tenant_id, values["currency_id"])
            try:
                row = await self.repo.update(tenant_id, account_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("An account with this code already exists") from exc
            if row is None:
                raise ResourceNotFoundError("Account not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ACCOUNTING_MODULE,
                entity_type="account",
                entity_id=row.id,
                old_values=old_values,
                new_values=_account_snapshot(row),
            )
            return await self.get(tenant_id, row.id)

    async def get_balance(
        self, tenant_id: UUID, account_id: UUID, *, as_of: date | None = None
    ) -> AccountBalanceResponse:
        from app.common.utils.currency import quantize_money
        from app.core.enums import JournalEntryStatus
        from app.erp.accounting.ledger.models import JournalEntry, JournalEntryLine
        from app.erp.exchange_rates.service import CurrencyService

        row = await self._require(tenant_id, account_id)
        as_of_date = as_of or date.today()
        statement = (
            select(
                func.coalesce(func.sum(JournalEntryLine.debit_base), 0),
                func.coalesce(func.sum(JournalEntryLine.credit_base), 0),
            )
            .select_from(JournalEntryLine)
            .join(
                JournalEntry,
                (JournalEntry.id == JournalEntryLine.journal_entry_id)
                & (JournalEntry.tenant_id == tenant_id)
                & (JournalEntry.deleted_at.is_(None))
                & (JournalEntry.status == JournalEntryStatus.POSTED.value),
            )
            .where(
                JournalEntryLine.tenant_id == tenant_id,
                JournalEntryLine.account_id == account_id,
                JournalEntry.entry_date <= as_of_date,
            )
        )
        debit, credit = (await self.session.execute(statement)).one()
        debit = quantize_money(debit)
        credit = quantize_money(credit)
        if row.account_type in {AccountType.ASSET.value, AccountType.EXPENSE.value}:
            signed = quantize_money(debit - credit)
        else:
            signed = quantize_money(credit - debit)
        currency_code = (await CurrencyService(self.session).get_base(tenant_id)).code
        return AccountBalanceResponse(
            account_id=row.id,
            as_of=as_of_date,
            debit=debit,
            credit=credit,
            signed_balance=signed,
            currency_code=currency_code,
        )

    async def get_period_balances(
        self,
        tenant_id: UUID,
        account_id: UUID,
        *,
        fiscal_year: int | None = None,
    ) -> AccountPeriodBalancesResponse:
        from app.common.utils.currency import quantize_money
        from app.core.enums import JournalEntryStatus
        from app.erp.accounting.ledger.models import JournalEntry, JournalEntryLine

        row = await self._require(tenant_id, account_id)
        config = await FiscalYearConfig.load(self.session, tenant_id)
        year = fiscal_year if fiscal_year is not None else config.year_for(date.today())
        fy_start, fy_end = config.bounds(year)
        currency_code = (await CurrencyService(self.session).get_base(tenant_id)).code

        statement = (
            select(
                JournalEntry.entry_date,
                JournalEntryLine.debit_base,
                JournalEntryLine.credit_base,
            )
            .select_from(JournalEntryLine)
            .join(
                JournalEntry,
                (JournalEntry.id == JournalEntryLine.journal_entry_id)
                & (JournalEntry.tenant_id == tenant_id)
                & (JournalEntry.deleted_at.is_(None))
                & (JournalEntry.status == JournalEntryStatus.POSTED.value),
            )
            .where(
                JournalEntryLine.tenant_id == tenant_id,
                JournalEntryLine.account_id == account_id,
                JournalEntry.entry_date <= fy_end,
            )
        )
        rows = (await self.session.execute(statement)).all()
        period_ranges = config.period_bounds(year)
        period_totals: dict[int, tuple[Decimal, Decimal]] = {
            period: (Decimal("0"), Decimal("0")) for period, _, _ in period_ranges
        }
        opening_debit = Decimal("0")
        opening_credit = Decimal("0")
        for entry_date, debit, credit in rows:
            debit = Decimal(debit)
            credit = Decimal(credit)
            if entry_date < fy_start:
                opening_debit += debit
                opening_credit += credit
                continue
            for period, start, end in period_ranges:
                if start <= entry_date <= end:
                    current = period_totals[period]
                    period_totals[period] = (current[0] + debit, current[1] + credit)
                    break

        def signed_balance(debit_total: Decimal, credit_total: Decimal) -> Decimal:
            if row.account_type in {AccountType.ASSET.value, AccountType.EXPENSE.value}:
                return quantize_money(debit_total - credit_total)
            return quantize_money(credit_total - debit_total)

        opening = signed_balance(opening_debit, opening_credit)
        running_debit = opening_debit
        running_credit = opening_credit
        periods: list[AccountPeriodBalance] = []
        for period, start, end in period_ranges:
            debit, credit = period_totals[period]
            running_debit += debit
            running_credit += credit
            periods.append(
                AccountPeriodBalance(
                    period=period,
                    from_date=start,
                    to_date=end,
                    debit=quantize_money(debit),
                    credit=quantize_money(credit),
                    closing=signed_balance(running_debit, running_credit),
                )
            )
        return AccountPeriodBalancesResponse(
            account_id=row.id,
            fiscal_year=year,
            currency_code=currency_code,
            opening=opening,
            periods=periods,
            closing=signed_balance(running_debit, running_credit),
        )

    async def delete(
        self, tenant_id: UUID, account_id: UUID, *, actor_user_id: UUID
    ) -> AccountResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, account_id)
            if row.is_system:
                raise ValidationError("System accounts cannot be deleted")
            if await self.repo.count_children(tenant_id, account_id) > 0:
                raise ValidationError("Cannot delete an account that still has children")
            if await self._has_gl_lines(tenant_id, account_id):
                raise ValidationError("Cannot delete an account that has journal lines")
            response = AccountResponse.model_validate(row)
            await self.repo.soft_delete(tenant_id, account_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ACCOUNTING_MODULE,
                entity_type="account",
                entity_id=account_id,
                old_values=_account_snapshot(row),
            )
            return response

    async def list_system_roles(self, tenant_id: UUID) -> list[SystemRoleMapping]:
        rows = await self.repo.list_all(tenant_id)
        by_role = {row.system_role: row for row in rows if row.system_role}
        mappings: list[SystemRoleMapping] = []
        for role in AccountSystemRole:
            mapped = by_role.get(role.value)
            mappings.append(
                SystemRoleMapping(
                    role=role,
                    account_id=mapped.id if mapped else None,
                    account_code=mapped.code if mapped else None,
                    account_name=mapped.name if mapped else None,
                )
            )
        return mappings

    async def map_system_role(
        self,
        tenant_id: UUID,
        role: AccountSystemRole,
        account_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> SystemRoleMapping:
        async with transaction(self.session):
            account = await self.require_postable(tenant_id, account_id)
            previous = await self.repo.get_by_system_role(tenant_id, role.value)
            if previous is not None and previous.id != account_id:
                previous.system_role = None
            account.system_role = role.value
            account.is_system = True
            account.updated_by = actor_user_id
            await self.session.flush()
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ACCOUNTING_MODULE,
                entity_type="account",
                entity_id=account.id,
                new_values={"system_role": role.value},
            )
            return SystemRoleMapping(
                role=role,
                account_id=account.id,
                account_code=account.code,
                account_name=account.name,
            )

    async def _validate_parent(
        self,
        tenant_id: UUID,
        parent_id: UUID | None,
        account_type: str,
        *,
        exclude_id: UUID | None = None,
    ) -> int:
        if parent_id is None:
            return 0
        parent = await self._require(tenant_id, parent_id)
        if not parent.is_group:
            raise ValidationError("Parent account must be a group")
        if parent.account_type != account_type:
            raise ValidationError("Parent must have the same account type")
        if exclude_id is not None:
            await self._assert_no_cycle(tenant_id, exclude_id, parent_id)
        return parent.depth + 1

    async def _assert_no_cycle(
        self, tenant_id: UUID, account_id: UUID, new_parent_id: UUID
    ) -> None:
        current: UUID | None = new_parent_id
        seen: set[UUID] = {account_id}
        while current is not None:
            if current in seen:
                raise ValidationError("Account hierarchy cannot contain a cycle")
            seen.add(current)
            row = await self.repo.get(tenant_id, current)
            current = row.parent_id if row is not None else None

    async def _has_gl_lines(self, tenant_id: UUID, account_id: UUID) -> bool:
        from app.erp.accounting.ledger.models import JournalEntryLine

        statement = (
            select(func.count())
            .select_from(JournalEntryLine)
            .where(
                JournalEntryLine.tenant_id == tenant_id,
                JournalEntryLine.account_id == account_id,
            )
        )
        return int(await self.session.scalar(statement) or 0) > 0

    async def _require(self, tenant_id: UUID, account_id: UUID) -> Account:
        row = await self.repo.get(tenant_id, account_id)
        if row is None:
            raise ResourceNotFoundError("Account not found")
        return row

    async def _parent_map(
        self, tenant_id: UUID, rows: list[Account]
    ) -> dict[UUID, Account]:
        parent_ids = {row.parent_id for row in rows if row.parent_id is not None}
        if not parent_ids:
            return {}
        parents = await self.repo.get_many(tenant_id, parent_ids)
        return {parent.id: parent for parent in parents}

    def _to_response(
        self,
        row: Account,
        parent_map: dict[UUID, Account],
        *,
        has_children: bool = False,
        has_journal_lines: bool = False,
    ) -> AccountResponse:
        parent = parent_map.get(row.parent_id) if row.parent_id is not None else None
        return AccountResponse.model_validate(row).model_copy(
            update={
                "parent_code": parent.code if parent is not None else None,
                "parent_name": parent.name if parent is not None else None,
                "has_children": has_children,
                "has_journal_lines": has_journal_lines,
            }
        )


def _account_snapshot(row: Account) -> dict[str, object]:
    return {
        "code": row.code,
        "name": row.name,
        "account_type": row.account_type,
        "account_subtype": row.account_subtype,
        "parent_id": str(row.parent_id) if row.parent_id else None,
        "is_group": row.is_group,
        "is_system": row.is_system,
        "system_role": row.system_role,
        "is_active": row.is_active,
        "is_blocked": row.is_blocked,
    }

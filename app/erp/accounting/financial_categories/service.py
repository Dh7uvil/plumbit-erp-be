"""Financial category use cases."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import ACCOUNTING_MODULE
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.core.enums import AccountSubtype, AccountType, AuditAction
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError, ValidationError
from app.db.session import transaction
from app.erp.accounting.financial_categories.models import FinancialCategory
from app.erp.accounting.financial_categories.repository import FinancialCategoryRepository
from app.erp.accounting.financial_categories.schemas import (
    FinancialCategoryCreate,
    FinancialCategoryResponse,
    FinancialCategoryUpdate,
)

_DEFAULT_CATEGORIES: tuple[tuple[str, AccountType, AccountSubtype | None], ...] = (
    ("Current assets", AccountType.ASSET, AccountSubtype.OTHER_CURRENT_ASSET),
    ("Fixed assets", AccountType.ASSET, AccountSubtype.FIXED_ASSET),
    ("Current liabilities", AccountType.LIABILITY, AccountSubtype.OTHER_CURRENT_LIABILITY),
    ("Equity", AccountType.EQUITY, AccountSubtype.EQUITY),
    ("Revenue", AccountType.INCOME, AccountSubtype.INCOME),
    ("Cost of sales", AccountType.EXPENSE, AccountSubtype.COGS),
    ("Operating expenses", AccountType.EXPENSE, AccountSubtype.EXPENSE),
)


def _snapshot(row: FinancialCategory) -> dict[str, object]:
    return {
        "name": row.name,
        "account_type": row.account_type,
        "account_subtype": row.account_subtype,
    }


class FinancialCategoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = FinancialCategoryRepository(session)
        self.audit = AuditWriter(session)

    async def ensure_defaults(self, tenant_id: UUID) -> None:
        rows, total = await self.repo.list(
            tenant_id, page=PageParams(page=1, page_size=1), common_filter=None
        )
        if total > 0:
            return
        for name, account_type, subtype in _DEFAULT_CATEGORIES:
            await self.repo.create(
                tenant_id,
                {
                    "name": name,
                    "account_type": account_type.value,
                    "account_subtype": subtype.value if subtype else None,
                },
            )

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        account_type: AccountType | None = None,
    ) -> tuple[list[FinancialCategoryResponse], int]:
        await self.ensure_defaults(tenant_id)
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            account_type=account_type.value if account_type else None,
        )
        return [FinancialCategoryResponse.model_validate(row) for row in rows], total

    async def list_all(self, tenant_id: UUID) -> list[FinancialCategoryResponse]:
        await self.ensure_defaults(tenant_id)
        rows, _ = await self.repo.list(
            tenant_id, page=PageParams(page=1, page_size=500), common_filter=None
        )
        return [FinancialCategoryResponse.model_validate(row) for row in rows]

    async def get(self, tenant_id: UUID, category_id: UUID) -> FinancialCategoryResponse:
        return FinancialCategoryResponse.model_validate(await self._require(tenant_id, category_id))

    async def create(
        self, tenant_id: UUID, payload: FinancialCategoryCreate, *, actor_user_id: UUID
    ) -> FinancialCategoryResponse:
        self._validate_subtype(payload.account_type, payload.account_subtype)
        async with transaction(self.session):
            try:
                row = await self.repo.create(
                    tenant_id,
                    {
                        "name": payload.name,
                        "account_type": payload.account_type.value,
                        "account_subtype": payload.account_subtype.value
                        if payload.account_subtype
                        else None,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A financial category with this name already exists"
                ) from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ACCOUNTING_MODULE,
                entity_type="financial_category",
                entity_id=row.id,
                new_values=_snapshot(row),
            )
            return FinancialCategoryResponse.model_validate(row)

    async def update(
        self,
        tenant_id: UUID,
        category_id: UUID,
        payload: FinancialCategoryUpdate,
        *,
        actor_user_id: UUID,
    ) -> FinancialCategoryResponse:
        values = payload.model_dump(exclude_unset=True)
        if "account_type" in values and values["account_type"] is not None:
            values["account_type"] = values["account_type"].value
        if "account_subtype" in values and values["account_subtype"] is not None:
            values["account_subtype"] = values["account_subtype"].value
        async with transaction(self.session):
            existing = await self._require(tenant_id, category_id)
            old_values = _snapshot(existing)
            account_type = AccountType(values.get("account_type", existing.account_type))
            subtype_raw = values.get("account_subtype", existing.account_subtype)
            subtype = AccountSubtype(subtype_raw) if subtype_raw else None
            self._validate_subtype(account_type, subtype)
            row = await self.repo.update(tenant_id, category_id, values)
            if row is None:
                raise ResourceNotFoundError("Financial category not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ACCOUNTING_MODULE,
                entity_type="financial_category",
                entity_id=row.id,
                old_values=old_values,
                new_values=_snapshot(row),
            )
            return FinancialCategoryResponse.model_validate(row)

    async def delete(
        self, tenant_id: UUID, category_id: UUID, *, actor_user_id: UUID
    ) -> FinancialCategoryResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, category_id)
            response = FinancialCategoryResponse.model_validate(row)
            await self.repo.delete(tenant_id, category_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ACCOUNTING_MODULE,
                entity_type="financial_category",
                entity_id=category_id,
                old_values=_snapshot(row),
            )
            return response

    async def _require(self, tenant_id: UUID, category_id: UUID) -> FinancialCategory:
        row = await self.repo.get(tenant_id, category_id)
        if row is None:
            raise ResourceNotFoundError("Financial category not found")
        return row

    @staticmethod
    def _validate_subtype(
        account_type: AccountType, account_subtype: AccountSubtype | None
    ) -> None:
        del account_type, account_subtype

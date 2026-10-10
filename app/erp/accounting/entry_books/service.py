"""Entry book master — per-type series and default cash/bank account."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import ACCOUNTING_MODULE
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.core.enums import AuditAction, VoucherType
from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.db.session import transaction
from app.erp.accounting.entry_books.models import EntryBook
from app.erp.accounting.entry_books.repository import EntryBookRepository
from app.erp.accounting.entry_books.schemas import EntryBookResponse, EntryBookUpdate

_DEFAULT_BOOKS: tuple[tuple[VoucherType, str, str], ...] = (
    (VoucherType.CASH_RECEIPT, "Cash Receipt", "CR"),
    (VoucherType.CASH_PAYMENT, "Cash Payment", "CP"),
    (VoucherType.BANK_RECEIPT, "Bank Receipt", "BR"),
    (VoucherType.BANK_PAYMENT, "Bank Payment", "BP"),
    (VoucherType.JOURNAL, "Journal Voucher", "JV"),
    (VoucherType.GENERAL_PURCHASE, "General Purchase", "GP"),
    (VoucherType.PAYMENT_VOUCHER, "Payment Voucher", "PV"),
)


class EntryBookService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = EntryBookRepository(session)
        self.audit = AuditWriter(session)

    async def ensure_defaults(self, tenant_id: UUID) -> None:
        missing: list[tuple[VoucherType, str, str]] = []
        for voucher_type, name, prefix in _DEFAULT_BOOKS:
            existing = await self.repo.get_by_voucher_type(tenant_id, voucher_type.value)
            if existing is None:
                missing.append((voucher_type, name, prefix))
        if not missing:
            return
        async with transaction(self.session):
            for voucher_type, name, prefix in missing:
                await self.repo.create(
                    tenant_id,
                    {
                        "voucher_type": voucher_type.value,
                        "name": name,
                        "series_prefix": prefix,
                        "default_account_id": None,
                        "is_active": True,
                    },
                )

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        voucher_type: VoucherType | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[EntryBookResponse], int]:
        await self.ensure_defaults(tenant_id)
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            voucher_type=voucher_type.value if voucher_type else None,
            is_active=is_active,
        )
        return [self._to_response(row) for row in rows], total

    async def list_all_active(self, tenant_id: UUID) -> list[EntryBookResponse]:
        await self.ensure_defaults(tenant_id)
        rows, _ = await self.repo.list(
            tenant_id,
            page=PageParams(page=1, page_size=100),
            common_filter=None,
            is_active=True,
        )
        return [self._to_response(row) for row in rows]

    async def get(self, tenant_id: UUID, entry_book_id: UUID) -> EntryBookResponse:
        await self.ensure_defaults(tenant_id)
        row = await self.repo.get(tenant_id, entry_book_id)
        if row is None:
            raise ResourceNotFoundError("Entry book not found")
        return self._to_response(row)

    async def resolve_series_prefix(self, tenant_id: UUID, voucher_type: VoucherType) -> str | None:
        await self.ensure_defaults(tenant_id)
        row = await self.repo.get_by_voucher_type(tenant_id, voucher_type.value)
        if row is None or not row.is_active:
            return None
        return row.series_prefix.strip() or None

    async def update(
        self,
        tenant_id: UUID,
        entry_book_id: UUID,
        payload: EntryBookUpdate,
        *,
        actor_user_id: UUID,
    ) -> EntryBookResponse:
        async with transaction(self.session):
            row = await self.repo.get(tenant_id, entry_book_id)
            if row is None:
                raise ResourceNotFoundError("Entry book not found")
            values = payload.model_dump(exclude_unset=True)
            if not values:
                raise ValidationError("No changes supplied")
            if "series_prefix" in values and not values["series_prefix"]:
                raise ValidationError("Series prefix cannot be empty")
            if "name" in values and not values["name"]:
                raise ValidationError("Name cannot be empty")
            updated = await self.repo.update(tenant_id, entry_book_id, values)
            assert updated is not None
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ACCOUNTING_MODULE,
                entity_type="entry_book",
                entity_id=entry_book_id,
                new_values=values,
            )
            return self._to_response(updated)

    @staticmethod
    def _to_response(row: EntryBook) -> EntryBookResponse:
        return EntryBookResponse.model_validate(row)

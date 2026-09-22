"""Charge type use cases."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import ACCOUNTING_MODULE
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.core.enums import AuditAction
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError, ValidationError
from app.db.session import transaction
from app.erp.accounting.accounts.service import AccountService
from app.erp.accounting.charge_types.models import ChargeType
from app.erp.accounting.charge_types.repository import ChargeTypeRepository
from app.erp.accounting.charge_types.schemas import (
    ChargeTypeCreate,
    ChargeTypeResponse,
    ChargeTypeUpdate,
)
from app.erp.accounting.models import Tax


def _snapshot(row: ChargeType) -> dict[str, object]:
    return {
        "code": row.code,
        "name": row.name,
        "sort_order": row.sort_order,
        "is_inventoriable": row.is_inventoriable,
        "default_account_id": str(row.default_account_id),
        "allocation_basis": row.allocation_basis,
        "default_tax_id": str(row.default_tax_id) if row.default_tax_id else None,
        "applies_to": row.applies_to,
        "is_active": row.is_active,
    }


class ChargeTypeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ChargeTypeRepository(session)
        self.accounts = AccountService(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        is_active: bool | None = None,
        applies_to: str | None = None,
    ) -> tuple[list[ChargeTypeResponse], int]:
        filters: dict[str, object] = {}
        if is_active is not None:
            filters["is_active"] = is_active
        if applies_to is not None:
            filters["applies_to"] = applies_to
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        return [ChargeTypeResponse.model_validate(row) for row in rows], total

    async def get(self, tenant_id: UUID, charge_type_id: UUID) -> ChargeTypeResponse:
        return ChargeTypeResponse.model_validate(await self._require(tenant_id, charge_type_id))

    async def require_active(self, tenant_id: UUID, charge_type_id: UUID) -> ChargeType:
        row = await self._require(tenant_id, charge_type_id)
        if not row.is_active:
            raise ValidationError("Charge type is inactive")
        return row

    async def create(
        self, tenant_id: UUID, payload: ChargeTypeCreate, *, actor_user_id: UUID
    ) -> ChargeTypeResponse:
        await self.accounts.require_postable(tenant_id, payload.default_account_id)
        if payload.default_tax_id is not None:
            await self._require_tax(tenant_id, payload.default_tax_id)
        async with transaction(self.session):
            try:
                values = payload.model_dump()
                values["allocation_basis"] = (
                    None if payload.allocation_basis is None else payload.allocation_basis.value
                )
                values["applies_to"] = payload.applies_to.value
                row = await self.repo.create(
                    tenant_id,
                    {
                        **values,
                        "created_by": actor_user_id,
                        "updated_by": actor_user_id,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError("A charge type with this code already exists") from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ACCOUNTING_MODULE,
                entity_type="charge_type",
                entity_id=row.id,
                new_values=_snapshot(row),
            )
            return ChargeTypeResponse.model_validate(row)

    async def update(
        self,
        tenant_id: UUID,
        charge_type_id: UUID,
        payload: ChargeTypeUpdate,
        *,
        actor_user_id: UUID,
    ) -> ChargeTypeResponse:
        values = payload.model_dump(exclude_unset=True)
        if "default_account_id" in values and values["default_account_id"] is not None:
            await self.accounts.require_postable(tenant_id, values["default_account_id"])
        if "default_tax_id" in values and values["default_tax_id"] is not None:
            await self._require_tax(tenant_id, values["default_tax_id"])
        if "allocation_basis" in values:
            basis = values["allocation_basis"]
            values["allocation_basis"] = None if basis is None else basis.value
        if "applies_to" in values and values["applies_to"] is not None:
            values["applies_to"] = values["applies_to"].value
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            existing = await self._require(tenant_id, charge_type_id)
            old_values = _snapshot(existing)
            try:
                row = await self.repo.update(tenant_id, charge_type_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("A charge type with this code already exists") from exc
            if row is None:
                raise ResourceNotFoundError("Charge type not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ACCOUNTING_MODULE,
                entity_type="charge_type",
                entity_id=row.id,
                old_values=old_values,
                new_values=_snapshot(row),
            )
            return ChargeTypeResponse.model_validate(row)

    async def delete(
        self, tenant_id: UUID, charge_type_id: UUID, *, actor_user_id: UUID
    ) -> ChargeTypeResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, charge_type_id)
            old_values = _snapshot(existing)
            row = await self.repo.soft_delete(tenant_id, charge_type_id)
            if row is None:
                raise ResourceNotFoundError("Charge type not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ACCOUNTING_MODULE,
                entity_type="charge_type",
                entity_id=row.id,
                old_values=old_values,
            )
            return ChargeTypeResponse.model_validate(row)

    async def _require(self, tenant_id: UUID, charge_type_id: UUID) -> ChargeType:
        row = await self.repo.get(tenant_id, charge_type_id)
        if row is None:
            raise ResourceNotFoundError("Charge type not found")
        return row

    async def _require_tax(self, tenant_id: UUID, tax_id: UUID) -> None:
        from sqlalchemy import select

        found = (
            await self.session.execute(
                select(Tax.id).where(
                    Tax.tenant_id == tenant_id,
                    Tax.id == tax_id,
                    Tax.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if found is None:
            raise ValidationError("Tax not found")

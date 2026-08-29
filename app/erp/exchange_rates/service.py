"""Currency and org-level daily exchange-rate use cases."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import ERP_MODULE
from app.auth.org_service import OrganizationService
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.datetime import today_in_timezone
from app.core.enums import AuditAction
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError, ValidationError
from app.db.session import transaction
from app.erp.exchange_rates.models import Currency
from app.erp.exchange_rates.repository import CurrencyRepository, ExchangeRateRepository
from app.erp.exchange_rates.schemas import (
    CurrencyCreate,
    CurrencyResponse,
    CurrencyUpdate,
    ExchangeRateResolveResponse,
    ExchangeRateResponse,
    ExchangeRateUpsert,
)


class CurrencyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CurrencyRepository(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        is_base: bool | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[CurrencyResponse], int]:
        filters: dict[str, object] = {}
        if is_base is not None:
            filters["is_base"] = is_base
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
        )
        return [CurrencyResponse.model_validate(row) for row in rows], total

    async def get(self, tenant_id: UUID, currency_id: UUID) -> CurrencyResponse:
        return CurrencyResponse.model_validate(await self._require(tenant_id, currency_id))

    async def get_base(self, tenant_id: UUID) -> CurrencyResponse:
        row = await self.repo.get_base(tenant_id)
        if row is None:
            raise ResourceNotFoundError("Base currency not found")
        return CurrencyResponse.model_validate(row)

    async def require_id(self, tenant_id: UUID, currency_id: UUID) -> UUID:
        await self._require(tenant_id, currency_id)
        return currency_id

    async def create(
        self,
        tenant_id: UUID,
        payload: CurrencyCreate,
        *,
        actor_user_id: UUID,
    ) -> CurrencyResponse:
        async with transaction(self.session):
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
                raise DuplicateResourceError("A currency with this code already exists") from exc
            if row.is_base:
                await self.repo.clear_base_except(tenant_id, row.id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ERP_MODULE,
                entity_type="currency",
                entity_id=row.id,
                new_values={"code": row.code, "is_base": row.is_base},
            )
            return CurrencyResponse.model_validate(row)

    async def update(
        self,
        tenant_id: UUID,
        currency_id: UUID,
        payload: CurrencyUpdate,
        *,
        actor_user_id: UUID,
    ) -> CurrencyResponse:
        values = payload.model_dump(exclude_unset=True)
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            row = await self._require(tenant_id, currency_id)
            if values.get("is_base") is False and row.is_base:
                raise ValidationError("Cannot unset the tenant base currency")
            try:
                updated = await self.repo.update(tenant_id, currency_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("A currency with this code already exists") from exc
            if updated is None:
                raise ResourceNotFoundError("Currency not found")
            if updated.is_base:
                await self.repo.clear_base_except(tenant_id, updated.id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ERP_MODULE,
                entity_type="currency",
                entity_id=updated.id,
                new_values={"code": updated.code, "is_base": updated.is_base},
            )
            return CurrencyResponse.model_validate(updated)

    async def delete(
        self,
        tenant_id: UUID,
        currency_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> CurrencyResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, currency_id)
            if row.is_base:
                raise ValidationError("Cannot delete the tenant base currency")
            response = CurrencyResponse.model_validate(row)
            await self.repo.soft_delete(tenant_id, currency_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ERP_MODULE,
                entity_type="currency",
                entity_id=currency_id,
                old_values={"code": row.code},
            )
            return response

    async def _require(self, tenant_id: UUID, currency_id: UUID) -> Currency:
        row = await self.repo.get(tenant_id, currency_id)
        if row is None:
            raise ResourceNotFoundError("Currency not found")
        return row


class ExchangeRateService:
    """Single conversion entry point for documents."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ExchangeRateRepository(session)
        self.currencies = CurrencyService(session)
        self.org = OrganizationService(session)
        self.audit = AuditWriter(session)

    async def list_for_date(
        self,
        tenant_id: UUID,
        *,
        effective_date: date | None = None,
    ) -> list[ExchangeRateResponse]:
        on_date = effective_date or await self._tenant_today(tenant_id)
        rows = await self.repo.list_for_date(tenant_id, effective_date=on_date)
        return [ExchangeRateResponse.model_validate(row) for row in rows]

    async def upsert(
        self,
        tenant_id: UUID,
        payload: ExchangeRateUpsert,
        *,
        actor_user_id: UUID,
    ) -> ExchangeRateResponse:
        async with transaction(self.session):
            base = await self.currencies.get_base(tenant_id)
            foreign = await self.currencies.get(tenant_id, payload.currency_id)
            if foreign.id == base.id:
                raise ValidationError("Cannot record an exchange rate for the base currency")
            on_date = payload.effective_date or await self._tenant_today(tenant_id)
            existing = await self.repo.get_for_pair_on_date(
                tenant_id,
                from_currency_id=foreign.id,
                to_currency_id=base.id,
                effective_date=on_date,
            )
            if existing is None:
                row = await self.repo.create(
                    tenant_id,
                    {
                        "from_currency_id": foreign.id,
                        "to_currency_id": base.id,
                        "effective_date": on_date,
                        "rate": payload.rate_to_base,
                        "created_by": actor_user_id,
                        "updated_by": actor_user_id,
                    },
                )
                action = AuditAction.CREATE
            else:
                existing.rate = payload.rate_to_base
                existing.updated_by = actor_user_id
                await self.session.flush()
                await self.session.refresh(existing, attribute_names=["updated_at"])
                row = existing
                action = AuditAction.UPDATE
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=action,
                module=ERP_MODULE,
                entity_type="exchange_rate",
                entity_id=row.id,
                new_values={
                    "from_currency_id": row.from_currency_id,
                    "rate": row.rate,
                    "effective_date": row.effective_date,
                },
            )
            return ExchangeRateResponse.model_validate(row)

    async def resolve(
        self,
        tenant_id: UUID,
        *,
        from_currency_id: UUID,
        to_currency_id: UUID | None = None,
        on_date: date | None = None,
    ) -> ExchangeRateResolveResponse:
        """Return the org rate for a pair on a calendar date. Never falls back."""

        effective = on_date or await self._tenant_today(tenant_id)
        await self.currencies.require_id(tenant_id, from_currency_id)
        target_id = to_currency_id
        if target_id is None:
            target_id = (await self.currencies.get_base(tenant_id)).id
        else:
            await self.currencies.require_id(tenant_id, target_id)

        if from_currency_id == target_id:
            return ExchangeRateResolveResponse(
                from_currency_id=from_currency_id,
                to_currency_id=target_id,
                effective_date=effective,
                rate=Decimal("1"),
            )

        row = await self.repo.get_for_pair_on_date(
            tenant_id,
            from_currency_id=from_currency_id,
            to_currency_id=target_id,
            effective_date=effective,
        )
        if row is None:
            raise ResourceNotFoundError("No exchange rate for this currency on the document date")
        return ExchangeRateResolveResponse(
            from_currency_id=row.from_currency_id,
            to_currency_id=row.to_currency_id,
            effective_date=row.effective_date,
            rate=row.rate,
        )

    async def _tenant_today(self, tenant_id: UUID) -> date:
        timezone = await self.org.get_timezone(tenant_id)
        return today_in_timezone(timezone)

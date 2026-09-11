"""Customer credit-limit evaluation. NULL limit is unlimited."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.catalog import CREDIT_CONTROL_OVERRIDE, ERP_MODULE
from app.auth.org_service import OrganizationService
from app.common.schemas.warnings import DocumentWarning
from app.common.services.audit import AuditWriter
from app.common.utils.currency import quantize_money
from app.common.utils.datetime import today_in_timezone, utcnow
from app.core.enums import (
    AuditAction,
    CreditLimitPolicy,
    OpenItemType,
    SalesOrderStatus,
)
from app.core.exceptions import CreditLimitExceededError
from app.core.permissions import has_permission
from app.crm.customers.service import CustomerService
from app.erp.accounting.open_items.service import OpenItemsService
from app.erp.credit_control.schemas import CreditExposure
from app.erp.exchange_rates.service import ExchangeRateService
from app.erp.sales_orders.models import SalesOrder

_ZERO = Decimal("0")
_OPEN_ORDER_STATUSES = frozenset({SalesOrderStatus.CONFIRMED.value})


class CreditControlService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.org = OrganizationService(session)
        self.customers = CustomerService(session)
        self.open_items = OpenItemsService(session)
        self.fx = ExchangeRateService(session)
        self.audit = AuditWriter(session)

    async def evaluate(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        additional_amount: Decimal = _ZERO,
        *,
        include_open_orders: bool | None = None,
    ) -> CreditExposure:
        settings = await self.org.get_money_movement_settings(tenant_id)
        customer = await self.customers.get(tenant_id, customer_id)
        include = (
            settings.credit_limit_include_open_orders
            if include_open_orders is None
            else include_open_orders
        )
        today = today_in_timezone(await self.org.get_timezone(tenant_id))
        posted_ar = opening_ar = unapplied_receipts = unapplied_credits = _ZERO
        for item in await self.open_items.list_ar_open_items(tenant_id, customer_id):
            amount = await self._to_currency(
                tenant_id,
                item.balance,
                from_currency_id=item.currency_id,
                to_currency_id=customer.currency_id,
                on_date=today,
            )
            if item.item_type == OpenItemType.SALES_INVOICE:
                posted_ar += amount
            elif item.item_type == OpenItemType.OPENING_AR:
                opening_ar += amount
            elif item.item_type == OpenItemType.CUSTOMER_PAYMENT:
                unapplied_receipts += amount
            elif item.item_type == OpenItemType.CREDIT_NOTE:
                unapplied_credits += amount
        open_orders = _ZERO
        if include:
            open_orders = await self._open_order_value(
                tenant_id, customer_id, customer.currency_id, on_date=today
            )
        additional = quantize_money(additional_amount)
        exposure = quantize_money(
            posted_ar + opening_ar + open_orders - unapplied_receipts - unapplied_credits
        )
        available = None
        if customer.credit_limit is not None:
            available = quantize_money(customer.credit_limit - exposure)
        return CreditExposure(
            customer_id=customer_id,
            currency_id=customer.currency_id,
            credit_limit=customer.credit_limit,
            exposure=exposure,
            this_document=additional,
            available=available,
            posted_ar=quantize_money(posted_ar),
            opening_ar=quantize_money(opening_ar),
            unapplied_receipts=quantize_money(unapplied_receipts),
            unapplied_credits=quantize_money(unapplied_credits),
            open_orders=quantize_money(open_orders),
            policy=settings.credit_limit_policy.value,
        )

    async def enforce(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        additional_amount: Decimal,
        *,
        actor_user_id: UUID,
        override_reason: str | None = None,
        include_open_orders: bool | None = None,
    ) -> list[DocumentWarning]:
        settings = await self.org.get_money_movement_settings(tenant_id)
        exposure = await self.evaluate(
            tenant_id,
            customer_id,
            additional_amount,
            include_open_orders=include_open_orders,
        )
        if (
            settings.credit_limit_policy == CreditLimitPolicy.OFF
            or exposure.credit_limit is None
        ):
            return []
        projected = quantize_money(exposure.exposure + additional_amount)
        if projected <= exposure.credit_limit:
            return []
        details = {
            "limit": str(exposure.credit_limit),
            "exposure": str(exposure.exposure),
            "this_document": str(quantize_money(additional_amount)),
            "available": str(exposure.available) if exposure.available is not None else None,
        }
        warning = DocumentWarning(
            code="CREDIT_LIMIT_EXCEEDED",
            message="This document exceeds the customer credit limit",
            details=details,
        )
        if settings.credit_limit_policy == CreditLimitPolicy.WARN:
            return [warning]
        reason = (override_reason or "").strip()
        can_override = has_permission(self.actor_permissions, CREDIT_CONTROL_OVERRIDE)
        if can_override and reason:
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.OVERRIDE,
                module=ERP_MODULE,
                entity_type="credit_control",
                entity_id=customer_id,
                new_values={
                    "reason": reason,
                    "limit": str(exposure.credit_limit),
                    "exposure": str(exposure.exposure),
                    "this_document": str(quantize_money(additional_amount)),
                    "overridden_at": utcnow().isoformat(),
                },
            )
            return [warning]
        raise CreditLimitExceededError(details=details)

    async def _open_order_value(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        currency_id: UUID,
        *,
        on_date,
    ) -> Decimal:
        statement = (
            select(SalesOrder)
            .options(selectinload(SalesOrder.lines))
            .where(
                SalesOrder.tenant_id == tenant_id,
                SalesOrder.customer_id == customer_id,
                SalesOrder.deleted_at.is_(None),
                SalesOrder.status.in_(_OPEN_ORDER_STATUSES),
            )
        )
        total = _ZERO
        for row in (await self.session.execute(statement)).scalars().all():
            ordered = sum((line.quantity for line in row.lines), _ZERO)
            invoiced = sum((line.qty_invoiced for line in row.lines), _ZERO)
            if ordered <= _ZERO:
                continue
            remaining = quantize_money(row.grand_total * (ordered - invoiced) / ordered)
            if remaining <= _ZERO:
                continue
            total += await self._to_currency(
                tenant_id,
                remaining,
                from_currency_id=row.currency_id,
                to_currency_id=currency_id,
                on_date=on_date,
            )
        return quantize_money(total)

    async def _to_currency(
        self,
        tenant_id: UUID,
        amount: Decimal,
        *,
        from_currency_id: UUID,
        to_currency_id: UUID,
        on_date,
    ) -> Decimal:
        if amount == _ZERO or from_currency_id == to_currency_id:
            return quantize_money(amount)
        rate = (
            await self.fx.resolve(
                tenant_id,
                from_currency_id=from_currency_id,
                to_currency_id=to_currency_id,
                on_date=on_date,
            )
        ).rate
        return quantize_money(amount * rate)

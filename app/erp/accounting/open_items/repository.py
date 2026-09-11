"""Payment allocation queries."""

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.enums import InvoiceDocumentStatus, PaymentAllocationSource
from app.erp.accounting.open_items.models import PaymentAllocation
from app.erp.customer_payments.models import CustomerPayment
from app.erp.supplier_payments.models import SupplierPayment

_ZERO = Decimal("0")
_NOTE_SOURCES = (
    PaymentAllocationSource.CREDIT_NOTE.value,
    PaymentAllocationSource.DEBIT_NOTE.value,
)


class PaymentAllocationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _posted_source_clause(self, tenant_id: UUID) -> ColumnElement[bool]:
        posted_customer = exists(
            select(1).where(
                CustomerPayment.id == PaymentAllocation.payment_id,
                CustomerPayment.tenant_id == tenant_id,
                CustomerPayment.status == InvoiceDocumentStatus.POSTED.value,
                CustomerPayment.deleted_at.is_(None),
            )
        )
        posted_supplier = exists(
            select(1).where(
                SupplierPayment.id == PaymentAllocation.payment_id,
                SupplierPayment.tenant_id == tenant_id,
                SupplierPayment.status == InvoiceDocumentStatus.POSTED.value,
                SupplierPayment.deleted_at.is_(None),
            )
        )
        return or_(
            and_(
                PaymentAllocation.payment_type == PaymentAllocationSource.CUSTOMER_PAYMENT.value,
                posted_customer,
            ),
            and_(
                PaymentAllocation.payment_type == PaymentAllocationSource.SUPPLIER_PAYMENT.value,
                posted_supplier,
            ),
            PaymentAllocation.payment_type.in_(_NOTE_SOURCES),
        )

    async def list_live_for_payment(
        self, tenant_id: UUID, payment_type: str, payment_id: UUID
    ) -> list[PaymentAllocation]:
        statement = select(PaymentAllocation).where(
            PaymentAllocation.tenant_id == tenant_id,
            PaymentAllocation.payment_type == payment_type,
            PaymentAllocation.payment_id == payment_id,
            PaymentAllocation.reversed_at.is_(None),
        )
        return list((await self.session.execute(statement)).scalars().all())

    async def list_live_for_item(
        self, tenant_id: UUID, item_type: str, item_id: UUID
    ) -> list[PaymentAllocation]:
        statement = select(PaymentAllocation).where(
            PaymentAllocation.tenant_id == tenant_id,
            PaymentAllocation.item_type == item_type,
            PaymentAllocation.item_id == item_id,
            PaymentAllocation.reversed_at.is_(None),
        )
        return list((await self.session.execute(statement)).scalars().all())

    async def allocated_for_item(self, tenant_id: UUID, item_type: str, item_id: UUID) -> Decimal:
        statement = select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(
            PaymentAllocation.tenant_id == tenant_id,
            PaymentAllocation.item_type == item_type,
            PaymentAllocation.item_id == item_id,
            PaymentAllocation.reversed_at.is_(None),
            self._posted_source_clause(tenant_id),
        )
        value = (await self.session.execute(statement)).scalar_one()
        return Decimal(str(value))

    async def allocated_for_items(
        self, tenant_id: UUID, item_type: str, item_ids: Sequence[UUID]
    ) -> dict[UUID, Decimal]:
        if not item_ids:
            return {}
        statement = (
            select(PaymentAllocation.item_id, func.coalesce(func.sum(PaymentAllocation.amount), 0))
            .where(
                PaymentAllocation.tenant_id == tenant_id,
                PaymentAllocation.item_type == item_type,
                PaymentAllocation.item_id.in_(list(item_ids)),
                PaymentAllocation.reversed_at.is_(None),
                self._posted_source_clause(tenant_id),
            )
            .group_by(PaymentAllocation.item_id)
        )
        rows = (await self.session.execute(statement)).all()
        return {item_id: Decimal(str(amount)) for item_id, amount in rows}

    async def has_live_for_item(self, tenant_id: UUID, item_type: str, item_id: UUID) -> bool:
        statement = (
            select(PaymentAllocation.id)
            .where(
                PaymentAllocation.tenant_id == tenant_id,
                PaymentAllocation.item_type == item_type,
                PaymentAllocation.item_id == item_id,
                PaymentAllocation.reversed_at.is_(None),
            )
            .limit(1)
        )
        return (await self.session.execute(statement)).scalar_one_or_none() is not None

    async def create(
        self,
        tenant_id: UUID,
        *,
        payment_type: str,
        payment_id: UUID,
        item_type: str,
        item_id: UUID,
        amount: Decimal,
        journal_entry_id: UUID | None = None,
    ) -> PaymentAllocation:
        row = PaymentAllocation(
            tenant_id=tenant_id,
            payment_type=payment_type,
            payment_id=payment_id,
            item_type=item_type,
            item_id=item_id,
            amount=amount,
            journal_entry_id=journal_entry_id,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete_live_for_payment(
        self, tenant_id: UUID, payment_type: str, payment_id: UUID
    ) -> None:
        await self.session.execute(
            delete(PaymentAllocation).where(
                PaymentAllocation.tenant_id == tenant_id,
                PaymentAllocation.payment_type == payment_type,
                PaymentAllocation.payment_id == payment_id,
                PaymentAllocation.reversed_at.is_(None),
            )
        )

"""Customer payment queries."""

import builtins
from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.core.enums import InvoiceDocumentStatus
from app.erp.accounting.customer_payments.models import CustomerPayment


class CustomerPaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            CustomerPayment,
            allowed_sort_fields=frozenset(
                {
                    "created_at",
                    "updated_at",
                    "document_number",
                    "payment_date",
                    "status",
                    "amount_received",
                }
            ),
            allowed_filter_fields=frozenset(
                {
                    "status",
                    "customer_id",
                    "proforma_invoice_id",
                    "sales_order_id",
                    "currency_id",
                    "payment_method",
                }
            ),
            search_fields=frozenset({"document_number", "reference", "notes"}),
        )

    async def get(
        self, tenant_id: UUID, payment_id: UUID, *, for_update: bool = False
    ) -> CustomerPayment | None:
        statement = self._repo.base_query(tenant_id).where(CustomerPayment.id == payment_id)
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
        extra_criteria: Sequence[ColumnElement[bool]] | None = None,
    ) -> tuple[Sequence[CustomerPayment], int]:
        return await self._repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
            extra_criteria=extra_criteria,
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> CustomerPayment:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, payment_id: UUID, values: Mapping[str, object]
    ) -> CustomerPayment | None:
        return await self._repo.update(tenant_id, payment_id, values)

    async def soft_delete(self, tenant_id: UUID, payment_id: UUID) -> CustomerPayment | None:
        return await self._repo.soft_delete(tenant_id, payment_id)

    async def list_for_customer(
        self, tenant_id: UUID, customer_id: UUID
    ) -> builtins.list[CustomerPayment]:
        statement = (
            self._repo.base_query(tenant_id)
            .where(
                CustomerPayment.customer_id == customer_id,
                CustomerPayment.status != InvoiceDocumentStatus.CANCELLED.value,
            )
            .order_by(CustomerPayment.payment_date, CustomerPayment.created_at)
        )
        return list((await self.session.execute(statement)).scalars().all())

    async def list_for_sales_order(
        self, tenant_id: UUID, sales_order_id: UUID
    ) -> builtins.list[CustomerPayment]:
        statement = (
            self._repo.base_query(tenant_id)
            .where(
                CustomerPayment.sales_order_id == sales_order_id,
                CustomerPayment.status != InvoiceDocumentStatus.CANCELLED.value,
            )
            .order_by(CustomerPayment.payment_date, CustomerPayment.created_at)
        )
        return list((await self.session.execute(statement)).scalars().all())

    async def list_for_proforma_invoice(
        self, tenant_id: UUID, proforma_invoice_id: UUID
    ) -> builtins.list[CustomerPayment]:
        statement = (
            self._repo.base_query(tenant_id)
            .where(
                CustomerPayment.proforma_invoice_id == proforma_invoice_id,
                CustomerPayment.status != InvoiceDocumentStatus.CANCELLED.value,
            )
            .order_by(CustomerPayment.payment_date, CustomerPayment.created_at)
        )
        return list((await self.session.execute(statement)).scalars().all())

    async def list_unapplied_for_pfi(
        self, tenant_id: UUID, customer_id: UUID, proforma_invoice_id: UUID
    ) -> builtins.list[CustomerPayment]:
        statement = (
            self._repo.base_query(tenant_id)
            .where(
                CustomerPayment.customer_id == customer_id,
                CustomerPayment.proforma_invoice_id == proforma_invoice_id,
                CustomerPayment.status == InvoiceDocumentStatus.POSTED.value,
                CustomerPayment.amount_unapplied > 0,
            )
            .order_by(CustomerPayment.payment_date, CustomerPayment.created_at)
        )
        return list((await self.session.execute(statement)).scalars().all())

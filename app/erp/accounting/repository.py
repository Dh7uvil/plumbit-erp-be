"""Accounting master queries."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.erp.accounting.models import DocumentSequence, PaymentTerm, Tax, TermsTemplate


class TaxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Tax,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name", "rate"}),
            allowed_filter_fields=frozenset({"tax_category", "is_default", "is_active"}),
            search_fields=frozenset({"name"}),
        )

    async def get(self, tenant_id: UUID, tax_id: UUID) -> Tax | None:
        return await self._repo.get(tenant_id, tax_id)

    async def get_default(self, tenant_id: UUID) -> Tax | None:
        statement = (
            select(Tax)
            .where(
                Tax.tenant_id == tenant_id,
                Tax.is_default.is_(True),
                Tax.deleted_at.is_(None),
            )
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_category(self, tenant_id: UUID, tax_category: str) -> Tax | None:
        statement = (
            select(Tax)
            .where(
                Tax.tenant_id == tenant_id,
                Tax.tax_category == tax_category,
                Tax.deleted_at.is_(None),
                Tax.is_active.is_(True),
            )
            .order_by(Tax.created_at.asc())
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[Tax], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Tax:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, tax_id: UUID, values: Mapping[str, object]
    ) -> Tax | None:
        return await self._repo.update(tenant_id, tax_id, values)

    async def soft_delete(self, tenant_id: UUID, tax_id: UUID) -> Tax | None:
        return await self._repo.soft_delete(tenant_id, tax_id)

    async def clear_default_except(self, tenant_id: UUID, tax_id: UUID) -> None:
        statement = select(Tax).where(
            Tax.tenant_id == tenant_id,
            Tax.is_default.is_(True),
            Tax.id != tax_id,
            Tax.deleted_at.is_(None),
        )
        result = await self.session.execute(statement)
        for row in result.scalars().all():
            row.is_default = False
        await self.session.flush()


class PaymentTermRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            PaymentTerm,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name", "days"}),
            allowed_filter_fields=frozenset({"is_active"}),
            search_fields=frozenset({"name"}),
        )

    async def get(self, tenant_id: UUID, term_id: UUID) -> PaymentTerm | None:
        return await self._repo.get(tenant_id, term_id)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[PaymentTerm], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> PaymentTerm:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, term_id: UUID, values: Mapping[str, object]
    ) -> PaymentTerm | None:
        return await self._repo.update(tenant_id, term_id, values)

    async def soft_delete(self, tenant_id: UUID, term_id: UUID) -> PaymentTerm | None:
        return await self._repo.soft_delete(tenant_id, term_id)


class TermsTemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            TermsTemplate,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name"}),
            allowed_filter_fields=frozenset({"is_default", "is_active"}),
            search_fields=frozenset({"name"}),
        )

    async def get(self, tenant_id: UUID, template_id: UUID) -> TermsTemplate | None:
        return await self._repo.get(tenant_id, template_id)

    async def get_default(self, tenant_id: UUID) -> TermsTemplate | None:
        statement = (
            select(TermsTemplate)
            .where(
                TermsTemplate.tenant_id == tenant_id,
                TermsTemplate.is_default.is_(True),
                TermsTemplate.deleted_at.is_(None),
            )
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[TermsTemplate], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> TermsTemplate:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, template_id: UUID, values: Mapping[str, object]
    ) -> TermsTemplate | None:
        return await self._repo.update(tenant_id, template_id, values)

    async def soft_delete(self, tenant_id: UUID, template_id: UUID) -> TermsTemplate | None:
        return await self._repo.soft_delete(tenant_id, template_id)

    async def clear_default_except(self, tenant_id: UUID, template_id: UUID) -> None:
        statement = select(TermsTemplate).where(
            TermsTemplate.tenant_id == tenant_id,
            TermsTemplate.is_default.is_(True),
            TermsTemplate.id != template_id,
            TermsTemplate.deleted_at.is_(None),
        )
        result = await self.session.execute(statement)
        for row in result.scalars().all():
            row.is_default = False
        await self.session.flush()


class DocumentSequenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            DocumentSequence,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "document_type", "series", "fiscal_year"}
            ),
            allowed_filter_fields=frozenset(
                {"document_type", "series", "fiscal_year", "is_active"}
            ),
            search_fields=frozenset({"series", "prefix"}),
        )

    async def get(self, tenant_id: UUID, sequence_id: UUID) -> DocumentSequence | None:
        return await self._repo.get(tenant_id, sequence_id)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[DocumentSequence], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> DocumentSequence:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, sequence_id: UUID, values: Mapping[str, object]
    ) -> DocumentSequence | None:
        return await self._repo.update(tenant_id, sequence_id, values)

    async def soft_delete(self, tenant_id: UUID, sequence_id: UUID) -> DocumentSequence | None:
        return await self._repo.soft_delete(tenant_id, sequence_id)

    async def lock_for_allocate(
        self,
        tenant_id: UUID,
        *,
        document_type: str,
        series: str,
        fiscal_year: int,
        prefix: str,
        padding: int = 6,
    ) -> DocumentSequence:
        insert_stmt = (
            pg_insert(DocumentSequence)
            .values(
                tenant_id=tenant_id,
                document_type=document_type,
                series=series,
                fiscal_year=fiscal_year,
                prefix=prefix,
                next_number=1,
                padding=padding,
            )
            .on_conflict_do_nothing(
                index_elements=["tenant_id", "document_type", "series", "fiscal_year"],
                index_where=text("deleted_at IS NULL"),
            )
        )
        await self.session.execute(insert_stmt)

        statement = (
            select(DocumentSequence)
            .where(
                DocumentSequence.tenant_id == tenant_id,
                DocumentSequence.document_type == document_type,
                DocumentSequence.series == series,
                DocumentSequence.fiscal_year == fiscal_year,
                DocumentSequence.deleted_at.is_(None),
            )
            .with_for_update()
        )
        result = await self.session.execute(statement)
        row = result.scalar_one()
        return row

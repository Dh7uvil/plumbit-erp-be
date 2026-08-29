"""Attachment queries."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.attachments.models import Attachment
from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams


class AttachmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Attachment,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "original_filename", "size_bytes"}
            ),
            allowed_filter_fields=frozenset({"entity_type", "entity_id"}),
            search_fields=frozenset({"original_filename"}),
        )

    async def get(self, tenant_id: UUID, attachment_id: UUID) -> Attachment | None:
        return await self._repo.get(tenant_id, attachment_id)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[Attachment], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Attachment:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, attachment_id: UUID, values: Mapping[str, object]
    ) -> Attachment | None:
        return await self._repo.update(tenant_id, attachment_id, values)

    async def soft_delete(self, tenant_id: UUID, attachment_id: UUID) -> Attachment | None:
        return await self._repo.soft_delete(tenant_id, attachment_id)

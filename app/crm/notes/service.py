"""Note use cases."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import CRM_MODULE
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.core.enums import AuditAction
from app.core.exceptions import ResourceNotFoundError
from app.crm.notes.models import Note
from app.crm.notes.repository import NoteRepository
from app.crm.notes.schemas import NoteCreate, NoteResponse, NoteUpdate
from app.crm.related import assert_related_entity_exists
from app.db.session import transaction


class NoteService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = NoteRepository(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        related_entity_type: str | None = None,
        related_entity_id: UUID | None = None,
    ) -> tuple[list[NoteResponse], int]:
        filters: dict[str, object] = {}
        if related_entity_type is not None:
            filters["related_entity_type"] = related_entity_type
        if related_entity_id is not None:
            filters["related_entity_id"] = related_entity_id
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        return [NoteResponse.model_validate(row) for row in rows], total

    async def get(self, tenant_id: UUID, note_id: UUID) -> NoteResponse:
        return NoteResponse.model_validate(await self._require(tenant_id, note_id))

    async def create(
        self, tenant_id: UUID, payload: NoteCreate, *, actor_user_id: UUID
    ) -> NoteResponse:
        async with transaction(self.session):
            await assert_related_entity_exists(
                self.session, tenant_id, payload.related_entity_type, payload.related_entity_id
            )
            row = await self.repo.create(
                tenant_id,
                {
                    "body": payload.body,
                    "related_entity_type": payload.related_entity_type.value,
                    "related_entity_id": payload.related_entity_id,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=CRM_MODULE,
                entity_type="note",
                entity_id=row.id,
                new_values=_note_snapshot(row),
            )
            return NoteResponse.model_validate(row)

    async def update(
        self,
        tenant_id: UUID,
        note_id: UUID,
        payload: NoteUpdate,
        *,
        actor_user_id: UUID,
    ) -> NoteResponse:
        values = payload.model_dump(exclude_unset=True)
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            existing = await self._require(tenant_id, note_id)
            old_values = _note_snapshot(existing)
            row = await self.repo.update(tenant_id, note_id, values)
            if row is None:
                raise ResourceNotFoundError("Note not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=CRM_MODULE,
                entity_type="note",
                entity_id=row.id,
                old_values=old_values,
                new_values=_note_snapshot(row),
            )
            return NoteResponse.model_validate(row)

    async def delete(self, tenant_id: UUID, note_id: UUID, *, actor_user_id: UUID) -> NoteResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, note_id)
            response = NoteResponse.model_validate(row)
            await self.repo.soft_delete(tenant_id, note_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=CRM_MODULE,
                entity_type="note",
                entity_id=note_id,
                old_values=_note_snapshot(row),
            )
            return response

    async def _require(self, tenant_id: UUID, note_id: UUID) -> Note:
        row = await self.repo.get(tenant_id, note_id)
        if row is None:
            raise ResourceNotFoundError("Note not found")
        return row


def _note_snapshot(row: Note) -> dict[str, object]:
    return {
        "body": row.body,
        "related_entity_type": row.related_entity_type,
        "related_entity_id": str(row.related_entity_id),
    }

"""User table column preference use cases."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.table_preferences.catalog import get_table_catalog
from app.common.table_preferences.normalize import merge_stored, validate_update
from app.common.table_preferences.repository import UserTablePreferenceRepository
from app.common.table_preferences.schemas import TablePreferenceResponse, TablePreferenceUpdate
from app.core.exceptions import ResourceNotFoundError
from app.db.session import transaction


class TablePreferenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = UserTablePreferenceRepository(session)

    def _require_catalog(self, table_key: str):
        entry = get_table_catalog(table_key)
        if entry is None:
            raise ResourceNotFoundError("Unknown table")
        return entry

    def _default_response(
        self,
        table_key: str,
        permissions: frozenset[str],
    ) -> TablePreferenceResponse:
        entry = self._require_catalog(table_key)
        return TablePreferenceResponse(
            table_key=table_key,
            visible_columns=entry.default_visible(permissions),
            column_order=entry.default_order(permissions),
            is_default=True,
        )

    async def get(
        self,
        tenant_id: UUID,
        user_id: UUID,
        table_key: str,
        *,
        permissions: frozenset[str],
    ) -> TablePreferenceResponse:
        entry = self._require_catalog(table_key)
        row = await self.repo.get(tenant_id, user_id, table_key)
        if row is None:
            return self._default_response(table_key, permissions)
        merged = merge_stored(
            entry,
            visible_columns=row.visible_columns,
            column_order=row.column_order,
            permissions=permissions,
        )
        return TablePreferenceResponse(
            table_key=table_key,
            visible_columns=merged.visible_columns,
            column_order=merged.column_order,
            is_default=False,
        )

    async def upsert(
        self,
        tenant_id: UUID,
        user_id: UUID,
        table_key: str,
        payload: TablePreferenceUpdate,
        *,
        permissions: frozenset[str],
    ) -> TablePreferenceResponse:
        entry = self._require_catalog(table_key)
        normalized = validate_update(
            entry,
            visible_columns=payload.visible_columns,
            column_order=payload.column_order,
            permissions=permissions,
        )
        try:
            async with transaction(self.session):
                await self.repo.upsert(
                    tenant_id,
                    user_id,
                    table_key,
                    visible_columns=normalized.visible_columns,
                    column_order=normalized.column_order,
                )
        except IntegrityError:
            async with transaction(self.session):
                await self.repo.upsert(
                    tenant_id,
                    user_id,
                    table_key,
                    visible_columns=normalized.visible_columns,
                    column_order=normalized.column_order,
                )
        return TablePreferenceResponse(
            table_key=table_key,
            visible_columns=normalized.visible_columns,
            column_order=normalized.column_order,
            is_default=False,
        )

    async def reset(
        self,
        tenant_id: UUID,
        user_id: UUID,
        table_key: str,
        *,
        permissions: frozenset[str],
    ) -> TablePreferenceResponse:
        self._require_catalog(table_key)
        async with transaction(self.session):
            await self.repo.delete(tenant_id, user_id, table_key)
        return self._default_response(table_key, permissions)

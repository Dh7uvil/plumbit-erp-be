"""Database access for append-only audit logs."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.auth.models import User
from app.common.models.audit_log import AuditLog
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.core.enums import AuditAction, AuditStatus

IDENTITY_AUDIT_MODULE = "identity"


class AuditLogRepository:
    """Tenant-scoped read queries for audit logs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _criteria(
        self,
        tenant_id: UUID,
        *,
        common_filter: BaseFilter | None = None,
        module: str | None = None,
        action: str | None = None,
        user_id: UUID | None = None,
    ) -> list[ColumnElement[bool]]:
        criteria: list[ColumnElement[bool]] = [AuditLog.tenant_id == tenant_id]
        if module is not None:
            criteria.append(AuditLog.module == module)
        if action is not None:
            criteria.append(AuditLog.action == action)
        if user_id is not None:
            criteria.append(AuditLog.user_id == user_id)
        if common_filter is not None:
            if common_filter.date_from is not None:
                criteria.append(AuditLog.created_at >= common_filter.date_from)
            if common_filter.date_to is not None:
                criteria.append(AuditLog.created_at <= common_filter.date_to)
            if common_filter.search is not None:
                search_term = f"%{common_filter.search}%"
                criteria.append(
                    or_(
                        AuditLog.action.ilike(search_term),
                        AuditLog.module.ilike(search_term),
                        AuditLog.entity_type.ilike(search_term),
                        AuditLog.ip_address.ilike(search_term),
                        User.name.ilike(search_term),
                        User.email.ilike(search_term),
                    )
                )
        return criteria

    def _statement(
        self,
        tenant_id: UUID,
        *,
        common_filter: BaseFilter | None = None,
        module: str | None = None,
        action: str | None = None,
        user_id: UUID | None = None,
    ) -> Select[tuple[AuditLog]]:
        statement = select(AuditLog)
        if common_filter is not None and common_filter.search is not None:
            statement = statement.outerjoin(
                User,
                (User.id == AuditLog.user_id) & (User.tenant_id == AuditLog.tenant_id),
            )
        return statement.where(
            *self._criteria(
                tenant_id,
                common_filter=common_filter,
                module=module,
                action=action,
                user_id=user_id,
            )
        )

    async def list_logs(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        module: str | None = None,
        action: str | None = None,
        user_id: UUID | None = None,
    ) -> tuple[Sequence[AuditLog], int]:
        allowed_sort = frozenset({"created_at", "action", "module"})
        sort_by = common_filter.sort_by if common_filter else "created_at"
        sort_order = common_filter.sort_order if common_filter else "desc"
        if sort_by not in allowed_sort:
            msg = f"sort field is not allowed: {sort_by}"
            raise ValueError(msg)
        sort_column = getattr(AuditLog, sort_by)
        ordering = sort_column.desc() if sort_order == "desc" else sort_column.asc()

        statement = (
            self._statement(
                tenant_id,
                common_filter=common_filter,
                module=module,
                action=action,
                user_id=user_id,
            )
            .order_by(ordering)
            .offset(page.offset)
            .limit(page.page_size)
        )
        count_base = select(func.count()).select_from(AuditLog)
        if common_filter is not None and common_filter.search is not None:
            count_base = count_base.outerjoin(
                User,
                (User.id == AuditLog.user_id) & (User.tenant_id == AuditLog.tenant_id),
            )
        count_statement = count_base.where(
            *self._criteria(
                tenant_id,
                common_filter=common_filter,
                module=module,
                action=action,
                user_id=user_id,
            )
        )
        result = await self.session.execute(statement)
        total = await self.session.scalar(count_statement)
        return result.scalars().all(), int(total or 0)

    async def summarize(
        self,
        tenant_id: UUID,
        *,
        common_filter: BaseFilter | None = None,
    ) -> tuple[int, int, int, int]:
        """Return total events, unique users, failed logins, and identity-module actions."""

        criteria = self._criteria(tenant_id, common_filter=common_filter)
        total = await self.session.scalar(
            select(func.count()).select_from(AuditLog).where(*criteria)
        )
        unique_users = await self.session.scalar(
            select(func.count(func.distinct(AuditLog.user_id)))
            .select_from(AuditLog)
            .where(*criteria, AuditLog.user_id.is_not(None))
        )
        failed_attempts = await self.session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                *criteria,
                AuditLog.action == AuditAction.LOGIN,
                AuditLog.status == AuditStatus.FAILED,
            )
        )
        admin_actions = await self.session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(*criteria, AuditLog.module == IDENTITY_AUDIT_MODULE)
        )
        return (
            int(total or 0),
            int(unique_users or 0),
            int(failed_attempts or 0),
            int(admin_actions or 0),
        )

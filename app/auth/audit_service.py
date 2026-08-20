"""Read APIs for the append-only audit trail."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.audit_repository import AuditLogRepository
from app.auth.models import User
from app.auth.org_repository import OrganizationRepository
from app.auth.schemas import AuditLogResponse, AuditLogSummaryResponse, AuditLogUserSummary
from app.common.models.audit_log import AuditLog
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams


class AuditLogService:
    """Paginated audit list and KPI summary for the current tenant."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AuditLogRepository(session)
        self.org = OrganizationRepository(session)

    async def list_logs(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        module: str | None = None,
        action: str | None = None,
        user_id: UUID | None = None,
    ) -> tuple[list[AuditLogResponse], int]:
        rows, total = await self.repo.list_logs(
            tenant_id,
            page=page,
            common_filter=common_filter,
            module=module,
            action=action,
            user_id=user_id,
        )
        user_ids = [row.user_id for row in rows if row.user_id is not None]
        users = await self.org.get_users_by_ids(tenant_id, user_ids)
        return [self._to_response(row, users) for row in rows], total

    async def summarize(
        self,
        tenant_id: UUID,
        *,
        common_filter: BaseFilter | None = None,
    ) -> AuditLogSummaryResponse:
        date_filter = None
        if common_filter is not None:
            date_filter = BaseFilter(
                date_from=common_filter.date_from,
                date_to=common_filter.date_to,
            )
        total_events, unique_users, failed_attempts, admin_actions = await self.repo.summarize(
            tenant_id,
            common_filter=date_filter,
        )
        return AuditLogSummaryResponse(
            total_events=total_events,
            unique_users=unique_users,
            failed_attempts=failed_attempts,
            admin_actions=admin_actions,
        )

    @staticmethod
    def _to_response(row: AuditLog, users: dict[UUID, User]) -> AuditLogResponse:
        user = users.get(row.user_id) if row.user_id is not None else None
        user_summary = AuditLogUserSummary.model_validate(user) if user is not None else None
        return AuditLogResponse(
            id=row.id,
            timestamp=row.created_at,
            user=user_summary,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            module=row.module,
            ip_address=row.ip_address,
            status=row.status,
        )

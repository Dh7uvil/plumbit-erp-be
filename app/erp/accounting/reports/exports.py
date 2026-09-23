"""Queue financial report exports and render them in the outbox worker."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.outbox.service import OutboxService
from app.core.config import get_settings
from app.core.enums import ReportExportStatus
from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.db.session import async_session_factory, transaction
from app.erp.accounting.reports.csv_export import rows_from_models, table_download
from app.erp.accounting.reports.models import ReportExportJob
from app.erp.accounting.reports.schemas import ReportExportCreate, ReportExportJobResponse

REPORT_EXPORT_EVENT = "accounting.report.export"
_ALLOWED = {
    "profit-and-loss",
    "balance-sheet",
    "cost-center-profit-and-loss",
    "fx-exposure",
    "budget-vs-actual",
}


class ReportExportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.outbox = OutboxService(session)

    async def enqueue(
        self, tenant_id: UUID, payload: ReportExportCreate, *, actor_user_id: UUID
    ) -> ReportExportJobResponse:
        if payload.report not in _ALLOWED:
            raise ValidationError("This report cannot be exported as a background job")
        async with transaction(self.session):
            job = ReportExportJob(
                tenant_id=tenant_id,
                report_key=payload.report,
                export_format=payload.export_format,
                status=ReportExportStatus.PENDING.value,
                params=dict(payload.params),
                created_by=actor_user_id,
                updated_by=actor_user_id,
                version=1,
            )
            self.session.add(job)
            await self.session.flush()
            await self.outbox.enqueue(
                tenant_id,
                event_type=REPORT_EXPORT_EVENT,
                aggregate_type="report_export_job",
                aggregate_id=job.id,
                payload={"job_id": str(job.id)},
                dedupe_key=f"report-export:{job.id}",
            )
            job_id = job.id
        if not get_settings().feature_background_workers_enabled:
            await self.render(tenant_id, job_id)
        return await self.get(tenant_id, job_id)

    async def get(self, tenant_id: UUID, job_id: UUID) -> ReportExportJobResponse:
        row = await self._require(tenant_id, job_id)
        return ReportExportJobResponse.model_validate(row)

    async def download(self, tenant_id: UUID, job_id: UUID) -> tuple[str, str, bytes]:
        row = await self._require(tenant_id, job_id)
        if (
            row.status != ReportExportStatus.READY.value
            or row.content is None
            or row.filename is None
        ):
            raise ValidationError("Export is not ready")
        media = {
            "csv": "text/csv",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "pdf": "application/pdf",
        }[row.export_format]
        return row.filename, media, bytes(row.content)

    async def render(self, tenant_id: UUID, job_id: UUID) -> None:
        async with transaction(self.session):
            row = await self._require(tenant_id, job_id, for_update=True)
            if row.status == ReportExportStatus.READY.value:
                return
            try:
                filename, content = await self._build(tenant_id, row)
            except Exception as exc:
                row.status = ReportExportStatus.FAILED.value
                row.error = str(exc)[:2000]
                row.version += 1
                await self.session.flush()
                return
            row.status = ReportExportStatus.READY.value
            row.filename = filename
            row.content = content
            row.error = None
            row.version += 1
            await self.session.flush()

    async def _build(self, tenant_id: UUID, row: ReportExportJob) -> tuple[str, bytes]:
        from app.erp.accounting.fx_revaluation.service import FxRevaluationService
        from app.erp.accounting.reports.service import ReportService

        params = {str(key): value for key, value in (row.params or {}).items()}
        reports = ReportService(self.session)
        data: BaseModel
        if row.report_key == "profit-and-loss":
            raw_count = params.get("period_count")
            period_count = (
                int(raw_count) if isinstance(raw_count, str) and raw_count.isdigit() else 1
            )
            data = await reports.profit_and_loss(
                tenant_id,
                from_date=_date(params, "from"),
                to_date=_date(params, "to"),
                include_ytd=params.get("include_ytd") == "true",
                period_count=period_count,
                budget_id=_uuid(params.get("budget_id")),
            )
            attr = "lines"
        elif row.report_key == "balance-sheet":
            data = await reports.balance_sheet(tenant_id, as_of=_date(params, "as_of"))
            attr = "lines"
        elif row.report_key == "cost-center-profit-and-loss":
            data = await reports.cost_center_profit_and_loss(
                tenant_id, from_date=_date(params, "from"), to_date=_date(params, "to")
            )
            attr = "sections"
        elif row.report_key == "budget-vs-actual":
            budget_id = _uuid(params.get("budget_id"))
            if budget_id is None:
                raise ValidationError("budget_id is required")
            data = await reports.budget_vs_actual(
                tenant_id,
                budget_id,
                from_date=_date(params, "from"),
                to_date=_date(params, "to"),
            )
            attr = "lines"
        else:
            as_of = _date(params, "as_of")
            data = await FxRevaluationService(self.session).exposure(tenant_id, as_of=as_of)
            attr = "lines"
        items = getattr(data, attr, None)
        if isinstance(items, list) and items:
            fields, table = rows_from_models(items)
        else:
            dumped = data.model_dump(mode="json")
            fields = [key for key, value in dumped.items() if not isinstance(value, list)]
            table = [{key: dumped.get(key) for key in fields}]
        response = table_download(
            f"{row.report_key}.{row.export_format}",
            fields,
            table,
            export_format=row.export_format,
            currency_code=getattr(data, "currency_code", None),
        )
        disposition = response.headers.get("content-disposition", "")
        filename = row.report_key + "." + row.export_format
        if "filename=" in disposition:
            filename = disposition.split("filename=", 1)[1].strip('"')
        body = response.body
        content = body if isinstance(body, bytes) else bytes(body)
        return filename, content

    async def _require(
        self, tenant_id: UUID, job_id: UUID, *, for_update: bool = False
    ) -> ReportExportJob:
        statement = select(ReportExportJob).where(
            ReportExportJob.tenant_id == tenant_id,
            ReportExportJob.id == job_id,
        )
        if for_update:
            statement = statement.with_for_update()
        row = (await self.session.execute(statement)).scalar_one_or_none()
        if row is None:
            raise ResourceNotFoundError("Report export not found")
        return row


def _date(params: dict[str, Any], key: str) -> date:
    raw = params.get(key)
    if not isinstance(raw, str) or not raw:
        raise ValidationError(f"{key} is required")
    return date.fromisoformat(raw[:10])


def _uuid(value: object) -> UUID | None:
    if not isinstance(value, str) or not value:
        return None
    return UUID(value)


async def handle_report_export(event: object) -> None:
    from app.common.outbox.models import OutboxEvent

    if not isinstance(event, OutboxEvent):
        return
    payload = event.payload or {}
    job_raw = payload.get("job_id")
    if not isinstance(job_raw, str):
        raise ValueError("Invalid report export payload")
    async with async_session_factory() as session:
        await ReportExportService(session).render(event.tenant_id, UUID(job_raw))

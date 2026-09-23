"""Recurring templates generate draft invoices and bills. They never post."""

from __future__ import annotations

import calendar
import copy
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import ACCOUNTING_MODULE
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.due_date import due_date_from_terms
from app.common.utils.datetime import utcnow
from app.core.enums import (
    AuditAction,
    RecurringDocumentKind,
    RecurringFrequency,
    RecurringTemplateStatus,
)
from app.core.exceptions import DocumentStaleError, ResourceNotFoundError, ValidationError
from app.db.session import transaction
from app.erp.accounting.recurring.models import RecurringGeneration, RecurringTemplate
from app.erp.accounting.recurring.repository import RecurringRepository
from app.erp.accounting.recurring.schemas import (
    RecurringGenerationResponse,
    RecurringTemplateCreate,
    RecurringTemplateResponse,
    RecurringTemplateUpdate,
)
from app.erp.purchase_invoices.models import PurchaseInvoice
from app.erp.purchase_invoices.schemas import PurchaseInvoiceCreate
from app.erp.purchase_invoices.service import PurchaseInvoiceService
from app.erp.sales_invoices.models import SalesInvoice
from app.erp.sales_invoices.schemas import SalesInvoiceCreate
from app.erp.sales_invoices.service import SalesInvoiceService

_HEADER_LINKS = (
    "sales_order_id",
    "source_quotation_id",
    "source_proforma_invoice_id",
    "purchase_order_id",
    "goods_receipt_id",
)
_LINE_LINKS = (
    "sales_order_line_id",
    "source_quotation_line_id",
    "source_proforma_invoice_line_id",
    "delivery_note_id",
    "delivery_note_line_id",
    "purchase_order_line_id",
    "goods_receipt_line_id",
)


def advance_date(current: date, frequency: str, interval: int, *, schedule_day: int) -> date:
    step = max(interval, 1)
    if frequency == RecurringFrequency.WEEKLY.value:
        return current + timedelta(days=7 * step)
    months = step
    if frequency == RecurringFrequency.QUARTERLY.value:
        months = 3 * step
    elif frequency == RecurringFrequency.YEARLY.value:
        months = 12 * step
    return _add_months_from_anchor(current, months, schedule_day)


def _add_months_from_anchor(current: date, months: int, schedule_day: int) -> date:
    month_index = current.month - 1 + months
    year = current.year + month_index // 12
    month = month_index % 12 + 1
    day = min(schedule_day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def run_marker(template_id: UUID, run_date: date) -> str:
    return f"[recurring:{template_id}:{run_date.isoformat()}]"


def _actions(row: RecurringTemplate) -> list[str]:
    if row.status == RecurringTemplateStatus.COMPLETED.value:
        return []
    actions = ["update"]
    if row.occurrences_generated == 0:
        actions.append("delete")
    if row.status == RecurringTemplateStatus.ACTIVE.value:
        actions.append("generate")
    return actions


class RecurringService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = RecurringRepository(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        document_kind: str | None = None,
    ) -> tuple[list[RecurringTemplateResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if document_kind is not None:
            filters["document_kind"] = document_kind
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        return [await self._response(tenant_id, row, include_history=False) for row in rows], total

    async def get(self, tenant_id: UUID, template_id: UUID) -> RecurringTemplateResponse:
        return await self._response(tenant_id, await self._require(tenant_id, template_id))

    async def create(
        self, tenant_id: UUID, payload: RecurringTemplateCreate, *, actor_user_id: UUID
    ) -> RecurringTemplateResponse:
        self._validate_payload(payload.document_kind, payload.template_payload)
        if payload.end_date is not None and payload.end_date < payload.next_run_date:
            raise ValidationError("end_date must be on or after next_run_date")
        async with transaction(self.session):
            row = await self.repo.create(
                tenant_id,
                {
                    "name": payload.name,
                    "document_kind": payload.document_kind.value,
                    "frequency": payload.frequency.value,
                    "interval": payload.interval,
                    "schedule_day": payload.next_run_date.day,
                    "next_run_date": payload.next_run_date,
                    "end_date": payload.end_date,
                    "max_occurrences": payload.max_occurrences,
                    "occurrences_generated": 0,
                    "status": RecurringTemplateStatus.ACTIVE.value,
                    "version": 1,
                    "template_payload": payload.template_payload,
                    "notes": payload.notes,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ACCOUNTING_MODULE,
                entity_type="recurring_template",
                entity_id=row.id,
                new_values={"name": row.name, "document_kind": row.document_kind},
            )
            return await self._response(tenant_id, row, include_history=False)

    async def update(
        self,
        tenant_id: UUID,
        template_id: UUID,
        payload: RecurringTemplateUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> RecurringTemplateResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, template_id, for_update=True)
            self._assert_version(row, expected_version)
            if row.status == RecurringTemplateStatus.COMPLETED.value:
                raise ValidationError("Completed templates cannot be edited")
            values: dict[str, object] = {
                "updated_by": actor_user_id,
                "version": row.version + 1,
            }
            data = payload.model_dump(exclude_unset=True, exclude={"version"})
            if "template_payload" in data and data["template_payload"] is not None:
                kind = RecurringDocumentKind(row.document_kind)
                self._validate_payload(kind, data["template_payload"])
            if "status" in data and data["status"] is not None:
                data["status"] = data["status"].value
            if "frequency" in data and data["frequency"] is not None:
                data["frequency"] = data["frequency"].value
            if "next_run_date" in data and data["next_run_date"] is not None:
                data["schedule_day"] = data["next_run_date"].day
            end_date = data.get("end_date", row.end_date)
            next_run = data.get("next_run_date", row.next_run_date)
            if end_date is not None and end_date < next_run:
                raise ValidationError("end_date must be on or after next_run_date")
            values.update(data)
            updated = await self.repo.update(tenant_id, template_id, values)
            if updated is None:
                raise ResourceNotFoundError("Recurring template not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ACCOUNTING_MODULE,
                entity_type="recurring_template",
                entity_id=template_id,
                new_values={"name": updated.name, "status": updated.status},
            )
            return await self._response(tenant_id, updated)

    async def delete(
        self, tenant_id: UUID, template_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> RecurringTemplateResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, template_id, for_update=True)
            self._assert_version(row, expected_version)
            if row.occurrences_generated > 0:
                raise ValidationError("Templates that have generated drafts cannot be deleted")
            response = await self._response(tenant_id, row, include_history=False)
            deleted = await self.repo.soft_delete(tenant_id, template_id)
            if deleted is None:
                raise ResourceNotFoundError("Recurring template not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ACCOUNTING_MODULE,
                entity_type="recurring_template",
                entity_id=template_id,
                old_values={"name": row.name},
            )
            return response

    async def materialize(
        self,
        tenant_id: UUID,
        template_id: UUID,
        *,
        actor_user_id: UUID,
        force: bool = False,
        today: date | None = None,
    ) -> RecurringTemplateResponse:
        """Create the next draft, or return the template when nothing is due."""

        as_of = today or date.today()
        reserved = await self._reserve(tenant_id, template_id, force=force, today=as_of)
        if reserved is None:
            return await self.get(tenant_id, template_id)
        run_date, kind = reserved
        existing_generation = await self.repo.generation_for_run(tenant_id, template_id, run_date)
        if existing_generation is not None and existing_generation.document_id is not None:
            await self._finish_run(
                tenant_id,
                template_id,
                run_date,
                document_id=existing_generation.document_id,
                document_number=existing_generation.document_number or "",
                actor_user_id=actor_user_id,
            )
            return await self.get(tenant_id, template_id)
        document_id, document_number = await self._find_marked(
            tenant_id, template_id, run_date, kind
        )
        if document_id is None:
            document_id, document_number = await self._create_draft(
                tenant_id, template_id, run_date, kind, actor_user_id=actor_user_id
            )
        if document_id is None or document_number is None:
            raise ValidationError("Recurring draft was not created")
        await self._finish_run(
            tenant_id,
            template_id,
            run_date,
            document_id=document_id,
            document_number=document_number,
            actor_user_id=actor_user_id,
        )
        return await self.get(tenant_id, template_id)

    async def run_due(
        self, tenant_id: UUID, *, actor_user_id: UUID, today: date | None = None
    ) -> int:
        as_of = today or date.today()
        rows = await self.repo.due_for_tenant(tenant_id, as_of)
        count = 0
        for row in rows:
            await self.materialize(
                tenant_id, row.id, actor_user_id=actor_user_id, force=False, today=as_of
            )
            count += 1
        return count

    async def _reserve(
        self, tenant_id: UUID, template_id: UUID, *, force: bool, today: date
    ) -> tuple[date, RecurringDocumentKind] | None:
        async with transaction(self.session):
            row = await self._require(tenant_id, template_id, for_update=True)
            if row.status != RecurringTemplateStatus.ACTIVE.value:
                raise ValidationError("Only active templates can generate drafts")
            if not force and row.next_run_date > today:
                return None
            if self._is_finished(row):
                row.status = RecurringTemplateStatus.COMPLETED.value
                row.version += 1
                await self.session.flush()
                return None
            existing = await self.repo.generation_for_run(tenant_id, template_id, row.next_run_date)
            if existing is not None and existing.document_id is not None:
                if row.next_run_date == existing.run_date:
                    return row.next_run_date, RecurringDocumentKind(row.document_kind)
                return None
            if existing is None:
                generation = RecurringGeneration(
                    tenant_id=tenant_id,
                    template_id=template_id,
                    run_date=row.next_run_date,
                    document_kind=row.document_kind,
                )
                self.session.add(generation)
                try:
                    await self.session.flush()
                except IntegrityError as exc:
                    raise ValidationError(
                        "A draft for this run date is already being generated"
                    ) from exc
            return row.next_run_date, RecurringDocumentKind(row.document_kind)

    async def _create_draft(
        self,
        tenant_id: UUID,
        template_id: UUID,
        run_date: date,
        kind: RecurringDocumentKind,
        *,
        actor_user_id: UUID,
    ) -> tuple[UUID, str]:
        row = await self._require(tenant_id, template_id)
        payload = await self._payload_for_run(tenant_id, row, run_date)
        if kind == RecurringDocumentKind.SALES_INVOICE:
            body = SalesInvoiceCreate.model_validate(payload)
            created_invoice = await SalesInvoiceService(
                self.session, actor_permissions=self.actor_permissions
            ).create(tenant_id, body, actor_user_id=actor_user_id)
            if created_invoice.status != "DRAFT":
                raise ValidationError("Recurring generation must leave the document as a draft")
            return created_invoice.id, created_invoice.document_number
        body_bill = PurchaseInvoiceCreate.model_validate(payload)
        created_bill = await PurchaseInvoiceService(
            self.session, actor_permissions=self.actor_permissions
        ).create(tenant_id, body_bill, actor_user_id=actor_user_id)
        if created_bill.status != "DRAFT":
            raise ValidationError("Recurring generation must leave the document as a draft")
        return created_bill.id, created_bill.document_number

    async def _finish_run(
        self,
        tenant_id: UUID,
        template_id: UUID,
        run_date: date,
        *,
        document_id: UUID,
        document_number: str,
        actor_user_id: UUID,
    ) -> None:
        async with transaction(self.session):
            row = await self._require(tenant_id, template_id, for_update=True)
            generation = await self.repo.generation_for_run(tenant_id, template_id, run_date)
            if generation is None:
                generation = RecurringGeneration(
                    tenant_id=tenant_id,
                    template_id=template_id,
                    run_date=run_date,
                    document_kind=row.document_kind,
                )
                self.session.add(generation)
            generation.document_id = document_id
            generation.document_number = document_number
            if row.next_run_date == run_date:
                row.occurrences_generated += 1
                row.last_document_id = document_id
                row.last_document_number = document_number
                row.last_run_at = utcnow()
                row.next_run_date = advance_date(
                    run_date, row.frequency, row.interval, schedule_day=row.schedule_day
                )
                if self._is_finished(row):
                    row.status = RecurringTemplateStatus.COMPLETED.value
                row.version += 1
                row.updated_by = actor_user_id
            await self.session.flush()
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ACCOUNTING_MODULE,
                entity_type="recurring_generation",
                entity_id=generation.id,
                new_values={
                    "template_id": str(template_id),
                    "document_id": str(document_id),
                    "run_date": run_date.isoformat(),
                },
            )

    async def _find_marked(
        self, tenant_id: UUID, template_id: UUID, run_date: date, kind: RecurringDocumentKind
    ) -> tuple[UUID, str] | tuple[None, None]:
        marker = run_marker(template_id, run_date)
        if kind == RecurringDocumentKind.SALES_INVOICE:
            invoice = (
                (
                    await self.session.execute(
                        select(SalesInvoice).where(
                            SalesInvoice.tenant_id == tenant_id,
                            SalesInvoice.deleted_at.is_(None),
                            SalesInvoice.notes.contains(marker),
                        )
                    )
                )
                .scalars()
                .first()
            )
            if invoice is None:
                return None, None
            return invoice.id, invoice.document_number
        bill = (
            (
                await self.session.execute(
                    select(PurchaseInvoice).where(
                        PurchaseInvoice.tenant_id == tenant_id,
                        PurchaseInvoice.deleted_at.is_(None),
                        PurchaseInvoice.notes.contains(marker),
                    )
                )
            )
            .scalars()
            .first()
        )
        if bill is None:
            return None, None
        return bill.id, bill.document_number

    async def _payload_for_run(
        self, tenant_id: UUID, row: RecurringTemplate, run_date: date
    ) -> dict[str, Any]:
        payload = copy.deepcopy(dict(row.template_payload))
        for key in _HEADER_LINKS:
            payload.pop(key, None)
        lines = payload.get("lines")
        if isinstance(lines, list):
            for line in lines:
                if isinstance(line, dict):
                    for key in _LINE_LINKS:
                        line.pop(key, None)
        marker = run_marker(row.id, run_date)
        notes = str(payload.get("notes") or "")
        if marker not in notes:
            payload["notes"] = f"{marker} {notes}".strip()
        payload["invoice_date"] = run_date.isoformat()
        payment_terms_id = payload.get("payment_terms_id")
        if payment_terms_id is not None:
            payload["due_date"] = (
                await due_date_from_terms(
                    self.session,
                    tenant_id,
                    UUID(str(payment_terms_id)),
                    run_date,
                )
            ).isoformat()
        else:
            payload.pop("due_date", None)
        return payload

    def _validate_payload(self, kind: RecurringDocumentKind, payload: dict[str, Any]) -> None:
        try:
            if kind == RecurringDocumentKind.SALES_INVOICE:
                SalesInvoiceCreate.model_validate(payload)
            else:
                PurchaseInvoiceCreate.model_validate(payload)
        except Exception as exc:
            raise ValidationError("Template payload is not a valid draft document") from exc

    def _is_finished(self, row: RecurringTemplate) -> bool:
        if row.end_date is not None and row.next_run_date > row.end_date:
            return True
        return row.max_occurrences is not None and row.occurrences_generated >= row.max_occurrences

    async def _require(
        self, tenant_id: UUID, template_id: UUID, *, for_update: bool = False
    ) -> RecurringTemplate:
        row = await self.repo.get(tenant_id, template_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Recurring template not found")
        return row

    def _assert_version(self, row: RecurringTemplate, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={"expected_version": expected_version, "actual_version": row.version}
            )

    async def _response(
        self, tenant_id: UUID, row: RecurringTemplate, *, include_history: bool = True
    ) -> RecurringTemplateResponse:
        response = RecurringTemplateResponse.model_validate(row)
        if include_history:
            history = await self.repo.generations_for(tenant_id, row.id)
            response.generations = [
                RecurringGenerationResponse.model_validate(item) for item in history
            ]
        response.available_actions = _actions(row)
        return response

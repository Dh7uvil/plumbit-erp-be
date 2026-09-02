"""Accounting master use cases."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import ERP_MODULE
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.core.enums import AuditAction, DocumentType, TaxCategory
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError
from app.db.session import transaction
from app.erp.accounting.models import DocumentSequence, PaymentTerm, Tax, TermsTemplate
from app.erp.accounting.repository import (
    DocumentSequenceRepository,
    PaymentTermRepository,
    TaxRepository,
    TermsTemplateRepository,
)
from app.erp.accounting.schemas import (
    DocumentSequenceCreate,
    DocumentSequenceResponse,
    DocumentSequenceUpdate,
    PaymentTermCreate,
    PaymentTermResponse,
    PaymentTermUpdate,
    TaxCreate,
    TaxResponse,
    TaxUpdate,
    TermsTemplateCreate,
    TermsTemplateResponse,
    TermsTemplateUpdate,
)


def _tax_snapshot(row: Tax) -> dict[str, object]:
    return {
        "name": row.name,
        "tax_category": row.tax_category,
        "rate": row.rate,
        "is_default": row.is_default,
        "is_active": row.is_active,
    }


def _payment_term_snapshot(row: PaymentTerm) -> dict[str, object]:
    return {
        "name": row.name,
        "days": row.days,
        "description": row.description,
        "is_active": row.is_active,
    }


def _terms_template_snapshot(row: TermsTemplate) -> dict[str, object]:
    return {
        "name": row.name,
        "body": row.body,
        "is_default": row.is_default,
        "is_active": row.is_active,
    }


def _document_sequence_snapshot(row: DocumentSequence) -> dict[str, object]:
    return {
        "document_type": row.document_type,
        "series": row.series,
        "fiscal_year": row.fiscal_year,
        "prefix": row.prefix,
        "next_number": row.next_number,
        "padding": row.padding,
        "is_active": row.is_active,
    }


class TaxService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TaxRepository(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        tax_category: str | None = None,
        is_default: bool | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[TaxResponse], int]:
        filters: dict[str, object] = {}
        if tax_category is not None:
            filters["tax_category"] = tax_category
        if is_default is not None:
            filters["is_default"] = is_default
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        return [TaxResponse.model_validate(row) for row in rows], total

    async def get(self, tenant_id: UUID, tax_id: UUID) -> TaxResponse:
        return TaxResponse.model_validate(await self._require(tenant_id, tax_id))

    async def get_default(self, tenant_id: UUID) -> TaxResponse:
        row = await self.repo.get_default(tenant_id)
        if row is None:
            raise ResourceNotFoundError("Default tax not found")
        return TaxResponse.model_validate(row)

    async def get_by_category(self, tenant_id: UUID, tax_category: TaxCategory) -> TaxResponse:
        row = await self.repo.get_by_category(tenant_id, tax_category.value)
        if row is None:
            raise ResourceNotFoundError(f"{tax_category.value} tax not found")
        return TaxResponse.model_validate(row)

    async def create(
        self, tenant_id: UUID, payload: TaxCreate, *, actor_user_id: UUID
    ) -> TaxResponse:
        async with transaction(self.session):
            values = payload.model_dump()
            values["tax_category"] = payload.tax_category.value
            values["created_by"] = actor_user_id
            values["updated_by"] = actor_user_id
            try:
                row = await self.repo.create(tenant_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("A tax with this name already exists") from exc
            if row.is_default:
                await self.repo.clear_default_except(tenant_id, row.id)
            await self._audit(
                tenant_id,
                actor_user_id,
                AuditAction.CREATE,
                row.id,
                new_values=_tax_snapshot(row),
            )
            return TaxResponse.model_validate(row)

    async def update(
        self, tenant_id: UUID, tax_id: UUID, payload: TaxUpdate, *, actor_user_id: UUID
    ) -> TaxResponse:
        values = payload.model_dump(exclude_unset=True)
        if "tax_category" in values and values["tax_category"] is not None:
            values["tax_category"] = str(values["tax_category"])
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            existing = await self._require(tenant_id, tax_id)
            old_values = _tax_snapshot(existing)
            try:
                row = await self.repo.update(tenant_id, tax_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("A tax with this name already exists") from exc
            if row is None:
                raise ResourceNotFoundError("Tax not found")
            if row.is_default:
                await self.repo.clear_default_except(tenant_id, row.id)
            await self._audit(
                tenant_id,
                actor_user_id,
                AuditAction.UPDATE,
                row.id,
                old_values=old_values,
                new_values=_tax_snapshot(row),
            )
            return TaxResponse.model_validate(row)

    async def delete(self, tenant_id: UUID, tax_id: UUID, *, actor_user_id: UUID) -> TaxResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, tax_id)
            response = TaxResponse.model_validate(row)
            await self.repo.soft_delete(tenant_id, tax_id)
            await self._audit(
                tenant_id,
                actor_user_id,
                AuditAction.DELETE,
                tax_id,
                old_values=_tax_snapshot(row),
            )
            return response

    async def _require(self, tenant_id: UUID, tax_id: UUID) -> Tax:
        row = await self.repo.get(tenant_id, tax_id)
        if row is None:
            raise ResourceNotFoundError("Tax not found")
        return row

    async def _audit(
        self,
        tenant_id: UUID,
        actor_user_id: UUID,
        action: AuditAction,
        entity_id: UUID,
        *,
        old_values: dict[str, object] | None = None,
        new_values: dict[str, object] | None = None,
    ) -> None:
        await self.audit.write(
            tenant_id=tenant_id,
            user_id=actor_user_id,
            action=action,
            module=ERP_MODULE,
            entity_type="tax",
            entity_id=entity_id,
            old_values=old_values,
            new_values=new_values,
        )


class PaymentTermService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PaymentTermRepository(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[PaymentTermResponse], int]:
        filters = {"is_active": is_active} if is_active is not None else None
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )
        return [PaymentTermResponse.model_validate(row) for row in rows], total

    async def get(self, tenant_id: UUID, term_id: UUID) -> PaymentTermResponse:
        return PaymentTermResponse.model_validate(await self._require(tenant_id, term_id))

    async def require_id(self, tenant_id: UUID, term_id: UUID) -> UUID:
        await self._require(tenant_id, term_id)
        return term_id

    async def create(
        self, tenant_id: UUID, payload: PaymentTermCreate, *, actor_user_id: UUID
    ) -> PaymentTermResponse:
        async with transaction(self.session):
            try:
                row = await self.repo.create(
                    tenant_id,
                    {
                        **payload.model_dump(),
                        "created_by": actor_user_id,
                        "updated_by": actor_user_id,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A payment term with this name already exists"
                ) from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ERP_MODULE,
                entity_type="payment_term",
                entity_id=row.id,
                new_values=_payment_term_snapshot(row),
            )
            return PaymentTermResponse.model_validate(row)

    async def update(
        self, tenant_id: UUID, term_id: UUID, payload: PaymentTermUpdate, *, actor_user_id: UUID
    ) -> PaymentTermResponse:
        values = payload.model_dump(exclude_unset=True)
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            existing = await self._require(tenant_id, term_id)
            old_values = _payment_term_snapshot(existing)
            try:
                row = await self.repo.update(tenant_id, term_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A payment term with this name already exists"
                ) from exc
            if row is None:
                raise ResourceNotFoundError("Payment term not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ERP_MODULE,
                entity_type="payment_term",
                entity_id=row.id,
                old_values=old_values,
                new_values=_payment_term_snapshot(row),
            )
            return PaymentTermResponse.model_validate(row)

    async def delete(
        self, tenant_id: UUID, term_id: UUID, *, actor_user_id: UUID
    ) -> PaymentTermResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, term_id)
            response = PaymentTermResponse.model_validate(row)
            await self.repo.soft_delete(tenant_id, term_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ERP_MODULE,
                entity_type="payment_term",
                entity_id=term_id,
                old_values=_payment_term_snapshot(row),
            )
            return response

    async def _require(self, tenant_id: UUID, term_id: UUID) -> PaymentTerm:
        row = await self.repo.get(tenant_id, term_id)
        if row is None:
            raise ResourceNotFoundError("Payment term not found")
        return row


class TermsTemplateService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TermsTemplateRepository(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        is_default: bool | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[TermsTemplateResponse], int]:
        filters: dict[str, object] = {}
        if is_default is not None:
            filters["is_default"] = is_default
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        return [TermsTemplateResponse.model_validate(row) for row in rows], total

    async def get(self, tenant_id: UUID, template_id: UUID) -> TermsTemplateResponse:
        return TermsTemplateResponse.model_validate(await self._require(tenant_id, template_id))

    async def get_default(self, tenant_id: UUID) -> TermsTemplateResponse | None:
        row = await self.repo.get_default(tenant_id)
        if row is None:
            return None
        return TermsTemplateResponse.model_validate(row)

    async def create(
        self, tenant_id: UUID, payload: TermsTemplateCreate, *, actor_user_id: UUID
    ) -> TermsTemplateResponse:
        async with transaction(self.session):
            try:
                row = await self.repo.create(
                    tenant_id,
                    {
                        **payload.model_dump(),
                        "created_by": actor_user_id,
                        "updated_by": actor_user_id,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A terms template with this name already exists"
                ) from exc
            if row.is_default:
                await self.repo.clear_default_except(tenant_id, row.id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ERP_MODULE,
                entity_type="terms_template",
                entity_id=row.id,
                new_values=_terms_template_snapshot(row),
            )
            return TermsTemplateResponse.model_validate(row)

    async def update(
        self,
        tenant_id: UUID,
        template_id: UUID,
        payload: TermsTemplateUpdate,
        *,
        actor_user_id: UUID,
    ) -> TermsTemplateResponse:
        values = payload.model_dump(exclude_unset=True)
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            existing = await self._require(tenant_id, template_id)
            old_values = _terms_template_snapshot(existing)
            try:
                row = await self.repo.update(tenant_id, template_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A terms template with this name already exists"
                ) from exc
            if row is None:
                raise ResourceNotFoundError("Terms template not found")
            if row.is_default:
                await self.repo.clear_default_except(tenant_id, row.id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ERP_MODULE,
                entity_type="terms_template",
                entity_id=row.id,
                old_values=old_values,
                new_values=_terms_template_snapshot(row),
            )
            return TermsTemplateResponse.model_validate(row)

    async def delete(
        self, tenant_id: UUID, template_id: UUID, *, actor_user_id: UUID
    ) -> TermsTemplateResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, template_id)
            response = TermsTemplateResponse.model_validate(row)
            await self.repo.soft_delete(tenant_id, template_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ERP_MODULE,
                entity_type="terms_template",
                entity_id=template_id,
                old_values=_terms_template_snapshot(row),
            )
            return response

    async def _require(self, tenant_id: UUID, template_id: UUID) -> TermsTemplate:
        row = await self.repo.get(tenant_id, template_id)
        if row is None:
            raise ResourceNotFoundError("Terms template not found")
        return row


class DocumentSequenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = DocumentSequenceRepository(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        document_type: str | None = None,
        series: str | None = None,
        fiscal_year: int | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[DocumentSequenceResponse], int]:
        filters: dict[str, object] = {}
        if document_type is not None:
            filters["document_type"] = document_type
        if series is not None:
            filters["series"] = series
        if fiscal_year is not None:
            filters["fiscal_year"] = fiscal_year
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        return [DocumentSequenceResponse.model_validate(row) for row in rows], total

    async def get(self, tenant_id: UUID, sequence_id: UUID) -> DocumentSequenceResponse:
        return DocumentSequenceResponse.model_validate(await self._require(tenant_id, sequence_id))

    async def create(
        self, tenant_id: UUID, payload: DocumentSequenceCreate, *, actor_user_id: UUID
    ) -> DocumentSequenceResponse:
        async with transaction(self.session):
            values = payload.model_dump()
            values["document_type"] = payload.document_type.value
            values["created_by"] = actor_user_id
            values["updated_by"] = actor_user_id
            try:
                row = await self.repo.create(tenant_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A document sequence for this type, series, and year already exists"
                ) from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ERP_MODULE,
                entity_type="document_sequence",
                entity_id=row.id,
                new_values=_document_sequence_snapshot(row),
            )
            return DocumentSequenceResponse.model_validate(row)

    async def update(
        self,
        tenant_id: UUID,
        sequence_id: UUID,
        payload: DocumentSequenceUpdate,
        *,
        actor_user_id: UUID,
    ) -> DocumentSequenceResponse:
        values = payload.model_dump(exclude_unset=True)
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            existing = await self._require(tenant_id, sequence_id)
            old_values = _document_sequence_snapshot(existing)
            row = await self.repo.update(tenant_id, sequence_id, values)
            if row is None:
                raise ResourceNotFoundError("Document sequence not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ERP_MODULE,
                entity_type="document_sequence",
                entity_id=row.id,
                old_values=old_values,
                new_values=_document_sequence_snapshot(row),
            )
            return DocumentSequenceResponse.model_validate(row)

    async def delete(
        self, tenant_id: UUID, sequence_id: UUID, *, actor_user_id: UUID
    ) -> DocumentSequenceResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, sequence_id)
            response = DocumentSequenceResponse.model_validate(row)
            await self.repo.soft_delete(tenant_id, sequence_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ERP_MODULE,
                entity_type="document_sequence",
                entity_id=sequence_id,
                old_values=_document_sequence_snapshot(row),
            )
            return response

    async def allocate(
        self,
        tenant_id: UUID,
        *,
        document_type: DocumentType,
        series: str,
        fiscal_year: int,
        prefix: str | None = None,
    ) -> str:
        """Lock the counter row and return the next formatted document number."""

        row = await self.repo.lock_for_allocate(
            tenant_id,
            document_type=document_type.value,
            series=series,
            fiscal_year=fiscal_year,
            prefix=prefix or series,
        )
        number = row.next_number
        row.next_number = number + 1
        await self.session.flush()
        return f"{row.prefix}-{fiscal_year}-{str(number).zfill(row.padding)}"

    async def _require(self, tenant_id: UUID, sequence_id: UUID) -> DocumentSequence:
        row = await self.repo.get(tenant_id, sequence_id)
        if row is None:
            raise ResourceNotFoundError("Document sequence not found")
        return row

"""Package compose, pack, and attach. Writes no stock and no reservation."""

from __future__ import annotations

import builtins
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import LOGISTICS_MODULE, PACKAGE_DELETE, PACKAGE_UPDATE
from app.auth.org_service import OrganizationService
from app.common.print.schemas import PrintDocumentResponse
from app.common.print.service import PrintService
from app.common.schemas.filters import BaseFilter
from app.common.schemas.packing import packing_persist
from app.common.schemas.pagination import PageParams
from app.common.schemas.related_documents import RelatedDocumentRef
from app.common.services.audit import AuditWriter
from app.common.utils.currency import quantize_quantity
from app.common.utils.datetime import today_in_timezone
from app.core.enums import AuditAction, DocumentType, PackageStatus, SalesOrderStatus
from app.core.exceptions import (
    DocumentStaleError,
    InvalidStatusTransitionError,
    ResourceNotFoundError,
    ValidationError,
)
from app.core.permissions import has_permission
from app.db.session import transaction
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.service import DocumentSequenceService
from app.erp.sales_orders.service import SalesOrderService
from app.inventory_management.delivery_notes.service import DeliveryNoteService
from app.inventory_management.packages.models import Package
from app.inventory_management.packages.repository import PackageRepository
from app.inventory_management.packages.schemas import (
    PackableLineResponse,
    PackageCreate,
    PackageLineInput,
    PackageLineResponse,
    PackageResponse,
    PackageUpdate,
)
from app.inventory_management.packages.workflow import (
    assert_editable,
    next_status,
    transition_actions,
)
from app.inventory_management.products.service import ProductService

_ZERO = Decimal("0")
_SERIES = "PKG"
_ACTION_PERMISSIONS: dict[str, str] = {
    "pack": PACKAGE_UPDATE,
    "cancel": PACKAGE_UPDATE,
}


class PackageService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = PackageRepository(session)
        self.sales_orders = SalesOrderService(session, actor_permissions=actor_permissions)
        self.delivery_notes = DeliveryNoteService(session, actor_permissions=actor_permissions)
        self.products = ProductService(session)
        self.org = OrganizationService(session)
        self.sequences = DocumentSequenceService(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        sales_order_id: UUID | None = None,
        delivery_note_id: UUID | None = None,
    ) -> tuple[list[PackageResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if sales_order_id is not None:
            filters["sales_order_id"] = sales_order_id
        if delivery_note_id is not None:
            filters["delivery_note_id"] = delivery_note_id
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        return [self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, package_id: UUID) -> PackageResponse:
        row = await self._require(tenant_id, package_id)
        response = self._to_response(row)
        response.related_documents = await self._related_documents(tenant_id, row)
        return response

    async def print_document(
        self,
        tenant_id: UUID,
        package_id: UUID,
        *,
        template_family: str = "china",
    ) -> PrintDocumentResponse:
        from app.common.utils.document_totals import format_address_snapshot
        from app.crm.customers.service import CustomerService

        row = await self.get(tenant_id, package_id)
        order = await self.sales_orders.get(tenant_id, row.sales_order_id)
        customer = await CustomerService(self.session).get(tenant_id, order.customer_id)
        printer = PrintService(self.session)
        family = template_family if template_family in {"uae", "china"} else "china"
        return await printer.assemble(
            tenant_id,
            document_type=DocumentType.PACKAGE.value,
            document_id=row.id,
            document_number=row.document_number,
            document_date=order.order_date,
            template_family=family,
            customer_code=customer.code,
            customer_name=customer.name,
            customer_address=format_address_snapshot(customer.billing_address),
            customer_trn=customer.trn,
            lpo_number=order.customer_po_number,
            notes=row.notes or row.shipping_marks,
            lines=[
                printer.commercial_line(line, index=index)
                for index, line in enumerate(row.lines, start=1)
            ],
        )

    async def import_drafts(
        self,
        tenant_id: UUID,
        *,
        filename: str | None,
        content: bytes,
        mapping: builtins.list[object],
        actor_user_id: UUID,
    ) -> object:
        from app.common.imex.commercial import (
            group_fill_forward,
            import_result,
            load_mapped_rows,
            packing_kwargs,
            require_line_quantity,
        )
        from app.common.imex.schemas import ImportRowError
        from app.core.constants import MAX_PAGE_SIZE

        rows = load_mapped_rows("package", filename=filename, content=content, mapping=mapping)
        created_ids: builtins.list[UUID] = []
        errors: builtins.list[ImportRowError] = []
        for (_key, items) in group_fill_forward(rows, ("sales_order_number",)).items():
            first_row_number, header = items[0]
            try:
                so_number = (header.get("sales_order_number") or "").strip()
                if not so_number:
                    raise ValidationError("Sales order is required")
                matches, _total = await self.sales_orders.list(
                    tenant_id,
                    page=PageParams(page=1, page_size=MAX_PAGE_SIZE),
                    common_filter=BaseFilter(search=so_number),
                )
                order = next(
                    (item for item in matches if item.document_number == so_number),
                    None,
                )
                if order is None:
                    raise ValidationError(f"Sales order {so_number} not found")
                used: set[UUID] = set()
                lines: builtins.list[PackageLineInput] = []
                for _row_number, item in items:
                    sku = (item.get("line.sku") or "").strip()
                    product = await self.products.find_by_sku(tenant_id, sku) if sku else None
                    match = None
                    for so_line in order.lines:
                        if so_line.id in used:
                            continue
                        if product is not None and so_line.product_id == product.id:
                            match = so_line
                            break
                        if (
                            product is None
                            and sku
                            and sku.lower() in (so_line.description or "").lower()
                        ):
                            match = so_line
                            break
                    if match is None:
                        raise ValidationError(f"No sales-order line for SKU {sku or '(blank)'}")
                    used.add(match.id)
                    packing = packing_kwargs(item, sku=sku)
                    packing.pop("description", None)
                    lines.append(
                        PackageLineInput(
                            sales_order_line_id=match.id,
                            product_id=match.product_id,
                            quantity=require_line_quantity(item),
                            **packing,
                        )
                    )
                created = await self.create(
                    tenant_id,
                    PackageCreate(sales_order_id=order.id, lines=lines),
                    actor_user_id=actor_user_id,
                )
                created_ids.append(created.id)
            except (ValidationError, ValueError) as exc:
                errors.append(ImportRowError(row_number=first_row_number, message=str(exc)))
        return import_result(created_ids, errors)

    async def export_rows(
        self,
        tenant_id: UUID,
        *,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        sales_order_id: UUID | None = None,
        delivery_note_id: UUID | None = None,
    ) -> builtins.list[builtins.list[object]]:
        from app.common.imex.commercial import commercial_export_row
        from app.core.constants import MAX_PAGE_SIZE

        exported: builtins.list[builtins.list[object]] = []
        page = 1
        while True:
            rows, total = await self.list(
                tenant_id,
                page=PageParams(page=page, page_size=MAX_PAGE_SIZE),
                common_filter=common_filter,
                status=status,
                sales_order_id=sales_order_id,
                delivery_note_id=delivery_note_id,
            )
            for row in rows:
                for line in row.lines:
                    exported.append(
                        commercial_export_row(row, line, party_id=row.sales_order_id)
                    )
            if len(rows) < MAX_PAGE_SIZE or page * MAX_PAGE_SIZE >= total:
                break
            page += 1
        return exported

    async def create(
        self, tenant_id: UUID, payload: PackageCreate, *, actor_user_id: UUID
    ) -> PackageResponse:
        async with transaction(self.session):
            header, line_rows = await self._build_draft(tenant_id, payload)
            fiscal_year = cast(int, header.pop("_fiscal_year"))
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.PACKAGE,
                series=_SERIES,
                fiscal_year=fiscal_year,
                prefix=_SERIES,
            )
            row = await self.repo.create(
                tenant_id,
                {
                    **header,
                    "document_number": number,
                    "status": PackageStatus.DRAFT.value,
                    "version": 1,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            await self.repo.replace_lines(tenant_id, row.id, line_rows)
            loaded = await self._require(tenant_id, row.id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=LOGISTICS_MODULE,
                entity_type="package",
                entity_id=row.id,
                new_values={"document_number": loaded.document_number},
            )
            return self._to_response(loaded)

    async def update(
        self,
        tenant_id: UUID,
        package_id: UUID,
        payload: PackageUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> PackageResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, package_id, for_update=True)
            assert_editable(PackageStatus(existing.status))
            self._assert_version(existing, expected_version)
            create_payload = await self._update_to_create(existing, payload)
            header, line_rows = await self._build_draft(
                tenant_id, create_payload, exclude_package_id=package_id
            )
            header.pop("_fiscal_year", None)
            header["updated_by"] = actor_user_id
            header["version"] = existing.version + 1
            await self.repo.update(tenant_id, package_id, header)
            await self.repo.replace_lines(tenant_id, package_id, line_rows)
            loaded = await self._require(tenant_id, package_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=LOGISTICS_MODULE,
                entity_type="package",
                entity_id=package_id,
            )
            return self._to_response(loaded)

    async def delete(
        self,
        tenant_id: UUID,
        package_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> PackageResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, package_id, for_update=True)
            if PackageStatus(row.status) != PackageStatus.DRAFT:
                raise InvalidStatusTransitionError("Only draft packages can be deleted")
            self._assert_version(row, expected_version)
            response = self._to_response(row)
            await self.repo.soft_delete(tenant_id, package_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=LOGISTICS_MODULE,
                entity_type="package",
                entity_id=package_id,
            )
            return response

    async def pack(
        self,
        tenant_id: UUID,
        package_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> PackageResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, package_id, for_update=True)
            self._assert_version(row, expected_version)
            target = next_status(PackageStatus(row.status), "pack")
            row.status = target.value
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.PACK,
                module=LOGISTICS_MODULE,
                entity_type="package",
                entity_id=package_id,
            )
            return self._to_response(row)

    async def cancel(
        self,
        tenant_id: UUID,
        package_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> PackageResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, package_id, for_update=True)
            self._assert_version(row, expected_version)
            target = next_status(PackageStatus(row.status), "cancel")
            row.status = target.value
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CANCEL,
                module=LOGISTICS_MODULE,
                entity_type="package",
                entity_id=package_id,
            )
            return self._to_response(row)

    async def attach_to_delivery_note(
        self,
        tenant_id: UUID,
        package_id: UUID,
        delivery_note_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> PackageResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, package_id, for_update=True)
            note = await self.delivery_notes.get(tenant_id, delivery_note_id)
            if row.sales_order_id != note.sales_order_id:
                raise ValidationError(
                    "Package and delivery note must belong to the same sales order"
                )
            if row.delivery_note_id is not None and row.delivery_note_id != delivery_note_id:
                raise ValidationError("This package is already attached to a delivery note")
            row.delivery_note_id = delivery_note_id
            row.updated_by = actor_user_id
            row.version += 1
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.LINK,
                module=LOGISTICS_MODULE,
                entity_type="package",
                entity_id=package_id,
                new_values={"delivery_note_id": str(delivery_note_id)},
            )
            return self._to_response(row)

    async def detach_from_delivery_note(
        self,
        tenant_id: UUID,
        package_id: UUID,
        delivery_note_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> PackageResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, package_id, for_update=True)
            if row.delivery_note_id != delivery_note_id:
                raise ValidationError("This package is not attached to the delivery note")
            row.delivery_note_id = None
            row.updated_by = actor_user_id
            row.version += 1
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UNLINK,
                module=LOGISTICS_MODULE,
                entity_type="package",
                entity_id=package_id,
            )
            return self._to_response(row)

    async def packable_lines(
        self, tenant_id: UUID, sales_order_id: UUID
    ) -> builtins.list[PackableLineResponse]:
        order = await self.sales_orders.get(tenant_id, sales_order_id)
        packed = await self.repo.packed_qty_by_sales_order_line(tenant_id, sales_order_id)
        rows: builtins.list[PackableLineResponse] = []
        for line in order.lines:
            qty_packed = packed.get(line.id, _ZERO)
            outstanding = quantize_quantity(line.quantity - qty_packed)
            if outstanding <= _ZERO:
                continue
            rows.append(
                PackableLineResponse(
                    sales_order_line_id=line.id,
                    product_id=line.product_id,
                    description=line.description,
                    unit_id=line.unit_id,
                    quantity=line.quantity,
                    qty_packed=qty_packed,
                    outstanding=outstanding,
                )
            )
        return rows

    async def _build_draft(
        self,
        tenant_id: UUID,
        payload: PackageCreate,
        *,
        exclude_package_id: UUID | None = None,
    ) -> tuple[dict[str, Any], builtins.list[dict[str, Any]]]:
        order = await self.sales_orders.get(tenant_id, payload.sales_order_id)
        if order.status not in {SalesOrderStatus.CONFIRMED, SalesOrderStatus.CLOSED}:
            raise ValidationError("Packages can only be created for a confirmed sales order")
        if payload.delivery_note_id is not None:
            note = await self.delivery_notes.get(tenant_id, payload.delivery_note_id)
            if note.sales_order_id != order.id:
                raise ValidationError("Delivery note does not belong to this sales order")
        packed = await self.repo.packed_qty_by_sales_order_line(
            tenant_id, payload.sales_order_id, exclude_package_id=exclude_package_id
        )
        so_lines = {line.id: line for line in order.lines}
        line_rows: builtins.list[dict[str, Any]] = []
        for index, line in enumerate(payload.lines, start=1):
            so_line = so_lines.get(line.sales_order_line_id)
            if so_line is None:
                raise ValidationError("Sales order line not found on this order")
            already = packed.get(line.sales_order_line_id, _ZERO)
            if already + line.quantity > so_line.quantity:
                raise ValidationError("Packed quantity cannot exceed the ordered quantity")
            packed[line.sales_order_line_id] = already + line.quantity
            product_id = line.product_id if line.product_id is not None else so_line.product_id
            unit_id = line.unit_id if line.unit_id is not None else so_line.unit_id
            line_rows.append(
                {
                    "line_number": index,
                    "sales_order_line_id": line.sales_order_line_id,
                    "product_id": product_id,
                    "quantity": quantize_quantity(line.quantity),
                    "unit_id": unit_id,
                    **packing_persist(line),
                }
            )
        fiscal_year = await year_for(
            self.session, tenant_id, today_in_timezone(await self.org.get_timezone(tenant_id))
        )
        header: dict[str, Any] = {
            "sales_order_id": payload.sales_order_id,
            "delivery_note_id": payload.delivery_note_id,
            "package_number": payload.package_number,
            "length": payload.length,
            "width": payload.width,
            "height": payload.height,
            "dimension_unit": payload.dimension_unit,
            "gross_weight": payload.gross_weight,
            "net_weight": payload.net_weight,
            "weight_unit": payload.weight_unit,
            "shipping_marks": payload.shipping_marks,
            "notes": payload.notes,
            "_fiscal_year": fiscal_year,
        }
        return header, line_rows

    async def _update_to_create(self, existing: Package, payload: PackageUpdate) -> PackageCreate:
        values = payload.model_dump(exclude_unset=True, exclude={"version"})
        if payload.lines is not None:
            lines = payload.lines
        else:
            lines = [
                PackageLineInput(
                    sales_order_line_id=line.sales_order_line_id,
                    product_id=line.product_id,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                )
                for line in existing.lines
            ]
        return PackageCreate(
            sales_order_id=existing.sales_order_id,
            delivery_note_id=values.get("delivery_note_id", existing.delivery_note_id),
            package_number=values.get("package_number", existing.package_number),
            length=values.get("length", existing.length),
            width=values.get("width", existing.width),
            height=values.get("height", existing.height),
            dimension_unit=values.get("dimension_unit", existing.dimension_unit),
            gross_weight=values.get("gross_weight", existing.gross_weight),
            net_weight=values.get("net_weight", existing.net_weight),
            weight_unit=values.get("weight_unit", existing.weight_unit),
            shipping_marks=values.get("shipping_marks", existing.shipping_marks),
            notes=values.get("notes", existing.notes),
            lines=lines,
        )

    def _to_response(self, row: Package) -> PackageResponse:
        status = PackageStatus(row.status)
        return PackageResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            status=status,
            version=row.version,
            sales_order_id=row.sales_order_id,
            delivery_note_id=row.delivery_note_id,
            package_number=row.package_number,
            length=row.length,
            width=row.width,
            height=row.height,
            dimension_unit=row.dimension_unit,
            gross_weight=row.gross_weight,
            net_weight=row.net_weight,
            weight_unit=row.weight_unit,
            shipping_marks=row.shipping_marks,
            notes=row.notes,
            available_actions=self._available_actions(status),
            lines=[PackageLineResponse.model_validate(line) for line in row.lines],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _related_documents(
        self, tenant_id: UUID, row: Package
    ) -> builtins.list[RelatedDocumentRef]:
        related: builtins.list[RelatedDocumentRef] = []
        order = await self.sales_orders.repo.get(tenant_id, row.sales_order_id)
        if order is not None:
            related.append(
                RelatedDocumentRef(
                    document_type=DocumentType.SALES_ORDER.value,
                    document_id=order.id,
                    document_number=order.document_number,
                    status=order.status,
                    relationship="source",
                    document_date=order.order_date,
                )
            )
        if row.delivery_note_id is not None:
            note = await self.delivery_notes.repo.get(tenant_id, row.delivery_note_id)
            if note is not None:
                related.append(
                    RelatedDocumentRef(
                        document_type=DocumentType.DELIVERY_NOTE.value,
                        document_id=note.id,
                        document_number=note.document_number,
                        status=note.status,
                        relationship="related",
                        document_date=note.document_date,
                    )
                )
        return related

    def _available_actions(self, status: PackageStatus) -> builtins.list[str]:
        actions: builtins.list[str] = []
        for action in transition_actions(status):
            required = _ACTION_PERMISSIONS[action]
            if has_permission(self.actor_permissions, required):
                actions.append(action)
        if status == PackageStatus.DRAFT and has_permission(self.actor_permissions, PACKAGE_DELETE):
            actions.append("delete")
        return actions

    def _assert_version(self, row: Package, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={"current_version": row.version, "provided_version": expected_version}
            )

    async def _require(
        self, tenant_id: UUID, package_id: UUID, *, for_update: bool = False
    ) -> Package:
        row = await self.repo.get(tenant_id, package_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Package not found")
        return row

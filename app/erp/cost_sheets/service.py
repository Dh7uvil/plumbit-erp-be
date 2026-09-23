"""Cost sheet planning, actuals pull, and landed-cost handoff (no GL)."""

from __future__ import annotations

import builtins
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    ACCOUNTING_MODULE,
    COST_SHEET_CLOSE,
    COST_SHEET_CONFIRM,
    COST_SHEET_DELETE,
    COST_SHEET_UPDATE,
    LANDED_COST_CREATE,
)
from app.auth.org_service import OrganizationService
from app.common.idempotency.service import IdempotencyService
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.currency import quantize_money, quantize_quantity
from app.common.utils.datetime import today_in_timezone
from app.core.enums import (
    AuditAction,
    CostSheetStatus,
    CostSheetType,
    DocumentType,
    InvoiceDocumentStatus,
    LandedCostAllocationMethod,
    PurchaseInvoiceLineType,
)
from app.core.exceptions import DocumentStaleError, ResourceNotFoundError, ValidationError
from app.core.permissions import has_permission
from app.db.session import transaction
from app.erp.accounting.charge_types.repository import ChargeTypeRepository
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.service import DocumentSequenceService
from app.erp.cost_sheets.models import CostSheet, CostSheetCharge, CostSheetLine
from app.erp.cost_sheets.repository import CostSheetRepository
from app.erp.cost_sheets.schemas import (
    CostSheetChargeInput,
    CostSheetChargeResponse,
    CostSheetCreate,
    CostSheetCreateLandedCostRequest,
    CostSheetLineInput,
    CostSheetLineResponse,
    CostSheetResponse,
    CostSheetTotals,
    CostSheetUpdate,
)
from app.erp.cost_sheets.workflow import assert_editable, next_status, transition_actions
from app.erp.exchange_rates.service import CurrencyService, ExchangeRateService
from app.erp.landed_costs.schemas import LandedCostCreateFromBills, LandedCostResponse
from app.erp.landed_costs.service import LandedCostService
from app.erp.proforma_invoices.models import ProformaInvoice
from app.erp.purchase_invoices.models import PurchaseInvoice, PurchaseInvoiceLine
from app.inventory_management.costing.service import CostingService
from app.inventory_management.goods_receipts.models import GoodsReceiptLine
from app.inventory_management.stock.service import SOURCE_GOODS_RECEIPT

_ZERO = Decimal("0")
_IMPORT_SERIES = "CSI"
_EXPORT_SERIES = "CSE"
_OTHER_SERIES = "CSO"
_ACTION_PERMISSIONS: dict[str, str] = {
    "confirm": COST_SHEET_CONFIRM,
    "close": COST_SHEET_CLOSE,
    "reopen": COST_SHEET_UPDATE,
    "pull_actuals": COST_SHEET_UPDATE,
    "create_landed_cost": LANDED_COST_CREATE,
}


class CostSheetService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = CostSheetRepository(session)
        self.charge_types = ChargeTypeRepository(session)
        self.costing = CostingService(session)
        self.landed_costs = LandedCostService(session, actor_permissions=actor_permissions)
        self.currencies = CurrencyService(session)
        self.fx = ExchangeRateService(session)
        self.org = OrganizationService(session)
        self.sequences = DocumentSequenceService(session)
        self.idempotency = IdempotencyService(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        sheet_type: str | None = None,
        shipment_id: UUID | None = None,
        purchase_order_id: UUID | None = None,
        supplier_id: UUID | None = None,
        customer_id: UUID | None = None,
        document_date_from: date | None = None,
        document_date_to: date | None = None,
    ) -> tuple[builtins.list[CostSheetResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if sheet_type is not None:
            filters["sheet_type"] = sheet_type
        if shipment_id is not None:
            filters["shipment_id"] = shipment_id
        if purchase_order_id is not None:
            filters["purchase_order_id"] = purchase_order_id
        if supplier_id is not None:
            filters["supplier_id"] = supplier_id
        if customer_id is not None:
            filters["customer_id"] = customer_id
        extra: builtins.list[Any] = []
        if document_date_from is not None:
            extra.append(CostSheet.document_date >= document_date_from)
        if document_date_to is not None:
            extra.append(CostSheet.document_date <= document_date_to)
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        return [await self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, cost_sheet_id: UUID) -> CostSheetResponse:
        row = await self._require(tenant_id, cost_sheet_id)
        return await self._to_response(row)

    async def create(
        self, tenant_id: UUID, payload: CostSheetCreate, *, actor_user_id: UUID
    ) -> CostSheetResponse:
        async with transaction(self.session):
            return await self._persist_create(tenant_id, payload, actor_user_id=actor_user_id)

    async def update(
        self,
        tenant_id: UUID,
        cost_sheet_id: UUID,
        payload: CostSheetUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int | None,
    ) -> CostSheetResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, cost_sheet_id, for_update=True)
            self._assert_version(row, expected_version, payload.version)
            assert_editable(CostSheetStatus(row.status))
            header, lines, charges = await self._merge_update(tenant_id, row, payload)
            await self.repo.update(
                tenant_id,
                cost_sheet_id,
                {
                    **header,
                    "version": row.version + 1,
                    "updated_by": actor_user_id,
                },
            )
            await self.repo.replace_children(
                tenant_id, cost_sheet_id, lines=lines, charges=charges
            )
            loaded = await self._require(tenant_id, cost_sheet_id)
            await self._sync_base_amounts(loaded)
            loaded = await self._require(tenant_id, cost_sheet_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ACCOUNTING_MODULE,
                entity_type="cost_sheet",
                entity_id=cost_sheet_id,
                new_values={"document_number": loaded.document_number},
            )
            return await self._to_response(loaded)

    async def delete(
        self,
        tenant_id: UUID,
        cost_sheet_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int | None,
    ) -> CostSheetResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, cost_sheet_id, for_update=True)
            self._assert_version(row, expected_version, None)
            if row.status != CostSheetStatus.DRAFT.value:
                raise ValidationError("Only draft cost sheets can be deleted")
            response = await self._to_response(row)
            await self.repo.soft_delete(tenant_id, cost_sheet_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ACCOUNTING_MODULE,
                entity_type="cost_sheet",
                entity_id=cost_sheet_id,
                old_values={"document_number": row.document_number},
            )
            return response

    async def confirm(
        self,
        tenant_id: UUID,
        cost_sheet_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int | None,
        version: int | None,
    ) -> CostSheetResponse:
        return await self._transition(
            tenant_id,
            cost_sheet_id,
            action="confirm",
            actor_user_id=actor_user_id,
            expected_version=expected_version,
            version=version,
        )

    async def close(
        self,
        tenant_id: UUID,
        cost_sheet_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int | None,
        version: int | None,
    ) -> CostSheetResponse:
        return await self._transition(
            tenant_id,
            cost_sheet_id,
            action="close",
            actor_user_id=actor_user_id,
            expected_version=expected_version,
            version=version,
        )

    async def reopen(
        self,
        tenant_id: UUID,
        cost_sheet_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int | None,
        version: int | None,
    ) -> CostSheetResponse:
        return await self._transition(
            tenant_id,
            cost_sheet_id,
            action="reopen",
            actor_user_id=actor_user_id,
            expected_version=expected_version,
            version=version,
        )

    async def pull_actuals(
        self,
        tenant_id: UUID,
        cost_sheet_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int | None,
        version: int | None,
    ) -> CostSheetResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, cost_sheet_id, for_update=True)
            self._assert_version(row, expected_version, version)
            if row.status == CostSheetStatus.CLOSED.value:
                raise ValidationError("Closed cost sheets cannot be refreshed")
            await self._refresh_actuals(tenant_id, row)
            await self.repo.update(
                tenant_id,
                cost_sheet_id,
                {"version": row.version + 1, "updated_by": actor_user_id},
            )
            loaded = await self._require(tenant_id, cost_sheet_id)
            return await self._to_response(loaded)

    async def create_landed_cost(
        self,
        tenant_id: UUID,
        cost_sheet_id: UUID,
        payload: CostSheetCreateLandedCostRequest,
        *,
        actor_user_id: UUID,
        expected_version: int | None,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> LandedCostResponse:
        if not has_permission(self.actor_permissions, LANDED_COST_CREATE):
            raise ValidationError("Missing permission to create landed costs")
        async with transaction(self.session):
            row = await self._require(tenant_id, cost_sheet_id, for_update=True)
            self._assert_version(row, expected_version, payload.version)
            if row.sheet_type != CostSheetType.IMPORT.value:
                raise ValidationError("Landed costs can only be created from import cost sheets")
            if row.status != CostSheetStatus.CONFIRMED.value:
                raise ValidationError("Confirm the cost sheet before creating a landed cost")
            if row.landed_cost_id is not None:
                raise ValidationError("This cost sheet already generated a landed cost")
            line_ids = [
                charge.purchase_invoice_line_id
                for charge in row.charges
                if charge.purchase_invoice_line_id is not None
            ]
            if not line_ids:
                raise ValidationError(
                    "Pull actuals first so charge rows reference posted bill lines"
                )
            grn_line_ids = [
                line.goods_receipt_line_id
                for line in row.lines
                if line.goods_receipt_line_id is not None
            ]
            if not grn_line_ids:
                raise ValidationError("Link goods lines to posted GRN lines before creating LC")
            goods_receipt_ids = await self._goods_receipt_ids_for_lines(tenant_id, grn_line_ids)
            document_date = payload.document_date or row.document_date
            lc_payload = LandedCostCreateFromBills(
                purchase_invoice_line_ids=line_ids,
                goods_receipt_ids=goods_receipt_ids,
                shipment_id=row.shipment_id,
                allocation_method=LandedCostAllocationMethod(row.allocation_method),
                document_date=document_date,
                notes=f"From cost sheet {row.document_number}",
            )
            lc = await self.landed_costs.create_from_bills(
                tenant_id,
                lc_payload,
                actor_user_id=actor_user_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                endpoint=endpoint,
            )
            await self.repo.update(
                tenant_id,
                cost_sheet_id,
                {
                    "landed_cost_id": lc.id,
                    "version": row.version + 1,
                    "updated_by": actor_user_id,
                },
            )
            return lc

    async def _persist_create(
        self, tenant_id: UUID, payload: CostSheetCreate, *, actor_user_id: UUID
    ) -> CostSheetResponse:
        header, lines, charges = await self._build_composed(tenant_id, payload)
        document_date = cast(date, header["document_date"])
        if payload.sheet_type == CostSheetType.IMPORT:
            party_id = payload.supplier_id
        elif payload.sheet_type == CostSheetType.EXPORT:
            party_id = payload.customer_id
        else:
            party_id = payload.supplier_id or payload.customer_id
        doc_type, series = self._numbering(payload.sheet_type)
        number = await self.sequences.allocate(
            tenant_id,
            document_type=doc_type,
            series=series,
            fiscal_year=await year_for(self.session, tenant_id, document_date),
            prefix=series,
            party_id=party_id,
        )
        row = await self.repo.create(
            tenant_id,
            {
                **header,
                "document_number": number,
                "sheet_type": payload.sheet_type.value,
                "status": CostSheetStatus.DRAFT.value,
                "version": 1,
                "created_by": actor_user_id,
                "updated_by": actor_user_id,
            },
        )
        await self.repo.replace_children(tenant_id, row.id, lines=lines, charges=charges)
        loaded = await self._require(tenant_id, row.id)
        await self._sync_base_amounts(loaded)
        loaded = await self._require(tenant_id, row.id)
        await self.audit.write(
            tenant_id=tenant_id,
            user_id=actor_user_id,
            action=AuditAction.CREATE,
            module=ACCOUNTING_MODULE,
            entity_type="cost_sheet",
            entity_id=row.id,
            new_values={"document_number": number, "sheet_type": payload.sheet_type.value},
        )
        return await self._to_response(loaded)

    async def _transition(
        self,
        tenant_id: UUID,
        cost_sheet_id: UUID,
        *,
        action: str,
        actor_user_id: UUID,
        expected_version: int | None,
        version: int | None,
    ) -> CostSheetResponse:
        permission = _ACTION_PERMISSIONS.get(action)
        if permission and not has_permission(self.actor_permissions, permission):
            raise ValidationError(f"Missing permission for {action}")
        async with transaction(self.session):
            row = await self._require(tenant_id, cost_sheet_id, for_update=True)
            self._assert_version(row, expected_version, version)
            if action == "reopen" and row.landed_cost_id is not None:
                raise ValidationError(
                    "Cannot reopen a cost sheet that already generated a landed cost"
                )
            current = CostSheetStatus(row.status)
            target = next_status(current, action)
            await self.repo.update(
                tenant_id,
                cost_sheet_id,
                {
                    "status": target.value,
                    "version": row.version + 1,
                    "updated_by": actor_user_id,
                },
            )
            loaded = await self._require(tenant_id, cost_sheet_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ACCOUNTING_MODULE,
                entity_type="cost_sheet",
                entity_id=cost_sheet_id,
                new_values={"status": target.value},
            )
            return await self._to_response(loaded)

    async def _build_composed(
        self, tenant_id: UUID, payload: CostSheetCreate
    ) -> tuple[
        dict[str, object],
        builtins.list[dict[str, object]],
        builtins.list[dict[str, object]],
    ]:
        document_date = payload.document_date or today_in_timezone(
            await self.org.get_timezone(tenant_id)
        )
        base = await self.currencies.get_base(tenant_id)
        base_currency_id = base.id
        currency_id = payload.currency_id or base_currency_id
        rate = payload.exchange_rate
        if rate is None:
            resolved = await self.fx.resolve(
                tenant_id,
                from_currency_id=currency_id,
                to_currency_id=base_currency_id,
                on_date=document_date,
            )
            rate = resolved.rate
        line_rows = self._line_rows(payload.lines)
        charge_rows = await self._charge_rows(tenant_id, payload.charges, payload.sheet_type)
        return (
            {
                "document_date": document_date,
                "shipment_id": payload.shipment_id,
                "purchase_order_id": payload.purchase_order_id,
                "supplier_id": payload.supplier_id,
                "customer_id": payload.customer_id,
                "proforma_invoice_id": payload.proforma_invoice_id,
                "currency_id": currency_id,
                "base_currency_id": base_currency_id,
                "exchange_rate": rate,
                "incoterm": payload.incoterm,
                "port_of_loading": payload.port_of_loading,
                "port_of_discharge": payload.port_of_discharge,
                "allocation_method": payload.allocation_method.value,
                "notes": payload.notes,
            },
            line_rows,
            charge_rows,
        )

    async def _merge_update(
        self, tenant_id: UUID, row: CostSheet, payload: CostSheetUpdate
    ) -> tuple[
        dict[str, object],
        builtins.list[dict[str, object]],
        builtins.list[dict[str, object]],
    ]:
        header: dict[str, object] = {}
        for field in (
            "document_date",
            "shipment_id",
            "purchase_order_id",
            "supplier_id",
            "customer_id",
            "proforma_invoice_id",
            "incoterm",
            "port_of_loading",
            "port_of_discharge",
            "notes",
        ):
            value = getattr(payload, field)
            if value is not None:
                header[field] = value
        if payload.currency_id is not None:
            header["currency_id"] = payload.currency_id
        if payload.exchange_rate is not None:
            header["exchange_rate"] = payload.exchange_rate
        if payload.allocation_method is not None:
            header["allocation_method"] = payload.allocation_method.value
        lines = (
            self._line_rows(payload.lines)
            if payload.lines is not None
            else [self._line_dict(line) for line in row.lines]
        )
        if payload.charges is not None:
            sheet_type = CostSheetType(row.sheet_type)
            charges = await self._charge_rows(tenant_id, payload.charges, sheet_type)
        else:
            charges = [self._charge_dict(charge) for charge in row.charges]
        return header, lines, charges

    def _line_rows(
        self, lines: builtins.list[CostSheetLineInput]
    ) -> builtins.list[dict[str, object]]:
        return [
            {
                "line_number": index + 1,
                "product_id": line.product_id,
                "unit_id": line.unit_id,
                "quantity": quantize_quantity(line.quantity),
                "base_rate": quantize_money(line.base_rate),
                "target_selling_price": (
                    quantize_money(line.target_selling_price)
                    if line.target_selling_price is not None
                    else None
                ),
                "goods_receipt_line_id": line.goods_receipt_line_id,
            }
            for index, line in enumerate(lines)
        ]

    def _line_dict(self, line: CostSheetLine) -> dict[str, object]:
        return {
            "line_number": line.line_number,
            "product_id": line.product_id,
            "unit_id": line.unit_id,
            "quantity": line.quantity,
            "base_rate": line.base_rate,
            "target_selling_price": line.target_selling_price,
            "goods_receipt_line_id": line.goods_receipt_line_id,
        }

    async def _charge_rows(
        self,
        tenant_id: UUID,
        charges: builtins.list[CostSheetChargeInput],
        sheet_type: CostSheetType,
    ) -> builtins.list[dict[str, object]]:
        rows: builtins.list[dict[str, object]] = []
        for index, charge in enumerate(charges):
            charge_type = await self.charge_types.get(tenant_id, charge.charge_type_id)
            if charge_type is None or not charge_type.is_active:
                raise ValidationError("Charge type not found or inactive")
            applies = charge_type.applies_to
            if sheet_type == CostSheetType.IMPORT and applies == "EXPORT":
                raise ValidationError(f"Charge {charge_type.code} does not apply to import sheets")
            if sheet_type == CostSheetType.EXPORT and applies == "IMPORT":
                raise ValidationError(f"Charge {charge_type.code} does not apply to export sheets")
            rows.append(
                {
                    "line_number": index + 1,
                    "charge_type_id": charge.charge_type_id,
                    "estimated_amount": quantize_money(charge.estimated_amount),
                    "actual_amount": (
                        quantize_money(charge.actual_amount)
                        if charge.actual_amount is not None
                        else None
                    ),
                    "allocation_basis": (
                        charge.allocation_basis.value if charge.allocation_basis else None
                    ),
                    "purchase_invoice_id": charge.purchase_invoice_id,
                    "purchase_invoice_line_id": charge.purchase_invoice_line_id,
                }
            )
        return rows

    def _charge_dict(self, charge: CostSheetCharge) -> dict[str, object]:
        return {
            "line_number": charge.line_number,
            "charge_type_id": charge.charge_type_id,
            "estimated_amount": charge.estimated_amount,
            "actual_amount": charge.actual_amount,
            "allocation_basis": charge.allocation_basis,
            "purchase_invoice_id": charge.purchase_invoice_id,
            "purchase_invoice_line_id": charge.purchase_invoice_line_id,
        }

    async def _refresh_actuals(self, tenant_id: UUID, row: CostSheet) -> None:
        bill_lines = await self._posted_expense_lines(tenant_id, row)
        by_charge: dict[UUID, PurchaseInvoiceLine] = {}
        for bill_line in bill_lines:
            if bill_line.charge_type_id is None:
                continue
            existing = by_charge.get(bill_line.charge_type_id)
            if existing is None or bill_line.amount > existing.amount:
                by_charge[bill_line.charge_type_id] = bill_line
        for charge in row.charges:
            matched_bill_line = by_charge.get(charge.charge_type_id)
            if matched_bill_line is None:
                continue
            charge.actual_amount = quantize_money(matched_bill_line.amount)
            charge.purchase_invoice_id = matched_bill_line.purchase_invoice_id
            charge.purchase_invoice_line_id = matched_bill_line.id
        for sheet_line in row.lines:
            if sheet_line.goods_receipt_line_id is None:
                continue
            grn_line = await self._grn_line(tenant_id, sheet_line.goods_receipt_line_id)
            if grn_line is None:
                continue
            layers = await self.costing.layers_for_source(
                tenant_id,
                SOURCE_GOODS_RECEIPT,
                grn_line.goods_receipt_id,
                sheet_line.goods_receipt_line_id,
            )
            if layers:
                sheet_line.base_rate = layers[0].landed_unit_cost
        await self.session.flush()

    async def _posted_expense_lines(
        self, tenant_id: UUID, row: CostSheet
    ) -> builtins.list[PurchaseInvoiceLine]:
        criteria = [
            PurchaseInvoiceLine.tenant_id == tenant_id,
            PurchaseInvoiceLine.line_type == PurchaseInvoiceLineType.EXPENSE.value,
            PurchaseInvoice.deleted_at.is_(None),
            PurchaseInvoice.status == InvoiceDocumentStatus.POSTED.value,
            PurchaseInvoiceLine.charge_type_id.is_not(None),
        ]
        if row.purchase_order_id is not None:
            criteria.append(PurchaseInvoice.purchase_order_id == row.purchase_order_id)
        elif row.supplier_id is not None:
            criteria.append(PurchaseInvoice.supplier_id == row.supplier_id)
        statement = (
            select(PurchaseInvoiceLine)
            .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceLine.purchase_invoice_id)
            .where(*criteria)
        )
        return list((await self.session.execute(statement)).scalars().all())

    async def _grn_line(self, tenant_id: UUID, line_id: UUID) -> GoodsReceiptLine | None:
        statement = select(GoodsReceiptLine).where(
            GoodsReceiptLine.tenant_id == tenant_id,
            GoodsReceiptLine.id == line_id,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def _goods_receipt_ids_for_lines(
        self, tenant_id: UUID, grn_line_ids: builtins.list[UUID]
    ) -> builtins.list[UUID]:
        statement = select(GoodsReceiptLine.goods_receipt_id).where(
            GoodsReceiptLine.tenant_id == tenant_id,
            GoodsReceiptLine.id.in_(grn_line_ids),
        )
        return list({row for row in (await self.session.execute(statement)).scalars().all()})

    async def _to_response(self, row: CostSheet) -> CostSheetResponse:
        charge_type_map = await self._charge_type_flags(tenant_id=row.tenant_id, row=row)
        totals, line_responses, charge_responses = await self._compute(
            row, charge_type_map=charge_type_map
        )
        status = CostSheetStatus(row.status)
        actions = transition_actions(status)
        if status == CostSheetStatus.CONFIRMED and row.landed_cost_id is not None:
            actions = [item for item in actions if item != "reopen"]
        if status != CostSheetStatus.CLOSED:
            if has_permission(self.actor_permissions, COST_SHEET_UPDATE):
                actions = [*actions, "pull_actuals"]
            if (
                status == CostSheetStatus.CONFIRMED
                and row.sheet_type == CostSheetType.IMPORT.value
                and row.landed_cost_id is None
                and has_permission(self.actor_permissions, LANDED_COST_CREATE)
            ):
                actions.append("create_landed_cost")
        if status == CostSheetStatus.DRAFT and has_permission(
            self.actor_permissions, COST_SHEET_DELETE
        ):
            actions.append("delete")
        return CostSheetResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            sheet_type=CostSheetType(row.sheet_type),
            status=status,
            version=row.version,
            document_date=row.document_date,
            shipment_id=row.shipment_id,
            purchase_order_id=row.purchase_order_id,
            supplier_id=row.supplier_id,
            customer_id=row.customer_id,
            proforma_invoice_id=row.proforma_invoice_id,
            currency_id=row.currency_id,
            base_currency_id=row.base_currency_id,
            exchange_rate=row.exchange_rate,
            incoterm=row.incoterm,
            port_of_loading=row.port_of_loading,
            port_of_discharge=row.port_of_discharge,
            allocation_method=LandedCostAllocationMethod(row.allocation_method),
            landed_cost_id=row.landed_cost_id,
            notes=row.notes,
            totals=totals,
            base_total=row.base_total,
            available_actions=actions,
            lines=line_responses,
            charges=charge_responses,
            created_at=row.created_at,
            updated_at=row.updated_at,
            created_by=row.created_by,
            updated_by=row.updated_by,
        )

    async def _sync_base_amounts(self, row: CostSheet) -> None:
        rate = row.exchange_rate
        line_base_total = _ZERO
        for line in row.lines:
            goods = quantize_money(line.quantity * line.base_rate)
            line.base_amount = quantize_money(goods * rate)
            line_base_total += line.base_amount
        charges_total = _ZERO
        for charge in row.charges:
            amount = (
                charge.actual_amount
                if charge.actual_amount is not None
                else charge.estimated_amount
            )
            charges_total += amount
        row.base_total = quantize_money(
            line_base_total + quantize_money(charges_total * rate)
        )
        await self.session.flush()

    async def _charge_type_flags(
        self, *, tenant_id: UUID, row: CostSheet
    ) -> dict[UUID, bool]:
        ids = {charge.charge_type_id for charge in row.charges}
        result: dict[UUID, bool] = {}
        for charge_type_id in ids:
            charge_type = await self.charge_types.get(tenant_id, charge_type_id)
            result[charge_type_id] = bool(charge_type and charge_type.is_inventoriable)
        return result

    async def _compute(
        self,
        row: CostSheet,
        *,
        charge_type_map: dict[UUID, bool],
    ) -> tuple[
        CostSheetTotals,
        builtins.list[CostSheetLineResponse],
        builtins.list[CostSheetChargeResponse],
    ]:
        inventoriable_est = _ZERO
        inventoriable_act: Decimal | None = _ZERO
        expensed_est = _ZERO
        expensed_act: Decimal | None = _ZERO
        charge_responses: builtins.list[CostSheetChargeResponse] = []
        for charge in row.charges:
            inventoriable = charge_type_map.get(charge.charge_type_id, False)
            if inventoriable:
                inventoriable_est += charge.estimated_amount
                if charge.actual_amount is not None:
                    inventoriable_act = (inventoriable_act or _ZERO) + charge.actual_amount
            else:
                expensed_est += charge.estimated_amount
                if charge.actual_amount is not None:
                    expensed_act = (expensed_act or _ZERO) + charge.actual_amount
            variance = None
            if charge.actual_amount is not None:
                variance = quantize_money(charge.actual_amount - charge.estimated_amount)
            charge_responses.append(
                CostSheetChargeResponse(
                    id=charge.id,
                    line_number=charge.line_number,
                    charge_type_id=charge.charge_type_id,
                    estimated_amount=charge.estimated_amount,
                    actual_amount=charge.actual_amount,
                    variance_amount=variance,
                    allocation_basis=(
                        LandedCostAllocationMethod(charge.allocation_basis)
                        if charge.allocation_basis
                        else None
                    ),
                    purchase_invoice_id=charge.purchase_invoice_id,
                    purchase_invoice_line_id=charge.purchase_invoice_line_id,
                    is_inventoriable=inventoriable,
                )
            )
        if inventoriable_act == _ZERO and not any(
            charge.actual_amount is not None
            for charge in row.charges
            if charge_type_map.get(charge.charge_type_id)
        ):
            inventoriable_act = None
        if expensed_act == _ZERO and not any(
            charge.actual_amount is not None
            for charge in row.charges
            if not charge_type_map.get(charge.charge_type_id, False)
        ):
            expensed_act = None

        line_goods_total = _ZERO
        line_responses: builtins.list[CostSheetLineResponse] = []
        line_values: builtins.list[tuple[Decimal, Decimal]] = []
        for line in row.lines:
            goods_value = quantize_money(line.quantity * line.base_rate)
            line_goods_total += goods_value
            line_values.append((line.quantity, goods_value))
        allocation_base = line_goods_total if line_goods_total > _ZERO else None

        weighted_est: Decimal | None = None
        weighted_act: Decimal | None = None
        total_qty = sum((qty for qty, _ in line_values), _ZERO)
        if total_qty > _ZERO and allocation_base:
            for line, (qty, goods_value) in zip(row.lines, line_values, strict=True):
                share = goods_value / allocation_base if allocation_base else _ZERO
                allocated_est = quantize_money(inventoriable_est * share)
                est_landed = quantize_money((goods_value + allocated_est) / qty)
                actual_landed = None
                if line.goods_receipt_line_id is not None:
                    grn_line = await self._grn_line(row.tenant_id, line.goods_receipt_line_id)
                    if grn_line is not None:
                        layers = await self.costing.layers_for_source(
                            row.tenant_id,
                            SOURCE_GOODS_RECEIPT,
                            grn_line.goods_receipt_id,
                            line.goods_receipt_line_id,
                        )
                        if layers:
                            actual_landed = layers[0].landed_unit_cost
                margin = None
                if line.target_selling_price and line.target_selling_price > _ZERO:
                    basis = actual_landed if actual_landed is not None else est_landed
                    margin = quantize_money(
                        (line.target_selling_price - basis) / line.target_selling_price * 100
                    )
                line_base = (
                    line.base_amount
                    if line.base_amount is not None
                    else quantize_money(goods_value * row.exchange_rate)
                )
                line_responses.append(
                    CostSheetLineResponse(
                        id=line.id,
                        line_number=line.line_number,
                        product_id=line.product_id,
                        unit_id=line.unit_id,
                        quantity=line.quantity,
                        base_rate=line.base_rate,
                        target_selling_price=line.target_selling_price,
                        goods_receipt_line_id=line.goods_receipt_line_id,
                        line_goods_value=goods_value,
                        base_amount=line_base,
                        estimated_landed_unit_cost=est_landed,
                        actual_landed_unit_cost=actual_landed,
                        expected_margin_pct=margin,
                    )
                )
            weighted_est = quantize_money(
                sum(
                    (resp.estimated_landed_unit_cost * resp.quantity for resp in line_responses),
                    _ZERO,
                )
                / total_qty
            )
            if any(resp.actual_landed_unit_cost is not None for resp in line_responses):
                weighted_act = quantize_money(
                    sum(
                        (
                            (resp.actual_landed_unit_cost or resp.estimated_landed_unit_cost)
                            * resp.quantity
                            for resp in line_responses
                        ),
                        _ZERO,
                    )
                    / total_qty
                )

        reference_selling: Decimal | None = None
        if row.proforma_invoice_id is not None:
            pf = await self._proforma(row.tenant_id, row.proforma_invoice_id)
            if pf is not None:
                reference_selling = pf.grand_total

        fob_total = line_goods_total if row.sheet_type == CostSheetType.EXPORT.value else None
        cif_total = None
        sheet_margin = None
        if row.sheet_type == CostSheetType.EXPORT.value:
            cif_total = quantize_money(line_goods_total + inventoriable_est)
            if reference_selling and reference_selling > _ZERO and weighted_est is not None:
                sheet_margin = quantize_money(
                    (reference_selling - weighted_est * total_qty) / reference_selling * 100
                )

        totals = CostSheetTotals(
            goods_value_estimated=line_goods_total,
            inventoriable_charges_estimated=inventoriable_est,
            inventoriable_charges_actual=inventoriable_act,
            expensed_charges_estimated=expensed_est,
            expensed_charges_actual=expensed_act,
            weighted_landed_unit_cost_estimated=weighted_est,
            weighted_landed_unit_cost_actual=weighted_act,
            fob_total=fob_total,
            cif_total=cif_total,
            reference_selling_total=reference_selling,
            sheet_expected_margin_pct=sheet_margin,
        )
        return totals, line_responses, charge_responses

    async def _proforma(self, tenant_id: UUID, proforma_id: UUID) -> ProformaInvoice | None:
        statement = select(ProformaInvoice).where(
            ProformaInvoice.tenant_id == tenant_id,
            ProformaInvoice.id == proforma_id,
            ProformaInvoice.deleted_at.is_(None),
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def _require(
        self, tenant_id: UUID, cost_sheet_id: UUID, *, for_update: bool = False
    ) -> CostSheet:
        row = await self.repo.get(tenant_id, cost_sheet_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Cost sheet not found")
        return row

    def _assert_version(
        self,
        row: CostSheet,
        expected_version: int | None,
        payload_version: int | None,
    ) -> None:
        version = payload_version if payload_version is not None else expected_version
        if version is not None and version != row.version:
            raise DocumentStaleError()

    @staticmethod
    def _numbering(sheet_type: CostSheetType) -> tuple[DocumentType, str]:
        if sheet_type == CostSheetType.IMPORT:
            return DocumentType.COST_SHEET_IMPORT, _IMPORT_SERIES
        if sheet_type == CostSheetType.EXPORT:
            return DocumentType.COST_SHEET_EXPORT, _EXPORT_SERIES
        return DocumentType.COST_SHEET_OTHER, _OTHER_SERIES

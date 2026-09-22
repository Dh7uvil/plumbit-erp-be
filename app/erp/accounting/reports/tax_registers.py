"""Sales/purchase registers and VAT 201 boxes from posted documents."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.common.utils.currency import quantize_money
from app.core.enums import AccountSystemRole, InvoiceDocumentStatus, TaxCategory
from app.core.exceptions import ValidationError
from app.crm.customers.models import Customer
from app.erp.accounting.models import Tax
from app.erp.accounting.reports.amounts import document_base_net_tax
from app.erp.accounting.reports.schemas import (
    TaxRegisterLine,
    TaxRegisterResponse,
    Vat201Box,
    Vat201Response,
    VatGlReconLine,
    VatGlReconResponse,
)
from app.erp.credit_notes.models import CreditNote
from app.erp.debit_notes.models import DebitNote
from app.erp.purchase_invoices.models import PurchaseInvoice
from app.erp.sales_invoices.models import SalesInvoice
from app.inventory_management.delivery_notes.models import DeliveryNote
from app.inventory_management.goods_receipts.models import GoodsReceipt
from app.inventory_management.warehouses.models import Warehouse

_ZERO = Decimal("0")


class TaxRegisters:
    async def sales_register(
        self,
        tenant_id: UUID,
        *,
        from_date: date,
        to_date: date,
        box: str | None = None,
    ) -> TaxRegisterResponse:
        if from_date > to_date:
            raise ValidationError("from_date must be on or before to_date")
        invoices = await self._posted_sales_invoices(tenant_id, from_date, to_date)
        notes = await self._posted_credit_notes(tenant_id, from_date, to_date)
        taxes = await self._taxes(tenant_id)
        names, trns = await self._party_names(
            tenant_id, {row.customer_id for row in invoices + notes}
        )
        zone_by_invoice = await self._invoice_designated(tenant_id, invoices)
        lines: list[TaxRegisterLine] = []
        for invoice in invoices:
            lines.append(
                self._sales_register_line(
                    invoice,
                    document_type="SALES_INVOICE",
                    party_name=names.get(invoice.customer_id, ""),
                    party_trn=invoice.customer_trn or trns.get(invoice.customer_id),
                    taxes=taxes,
                    is_designated_zone=zone_by_invoice.get(invoice.id, False),
                    sign=Decimal("1"),
                )
            )
        for note in notes:
            lines.append(
                self._credit_register_line(
                    note,
                    party_name=names.get(note.customer_id, ""),
                    party_trn=trns.get(note.customer_id),
                    taxes=taxes,
                    sign=Decimal("-1"),
                )
            )
        if box:
            lines = [line for line in lines if self._line_matches_box(line, box)]
        return await self._register_response(tenant_id, from_date, to_date, lines)

    async def purchase_register(
        self,
        tenant_id: UUID,
        *,
        from_date: date,
        to_date: date,
        box: str | None = None,
    ) -> TaxRegisterResponse:
        if from_date > to_date:
            raise ValidationError("from_date must be on or before to_date")
        bills = await self._posted_bills(tenant_id, from_date, to_date)
        notes = await self._posted_debit_notes(tenant_id, from_date, to_date)
        taxes = await self._taxes(tenant_id)
        names, trns = await self._party_names(tenant_id, {row.supplier_id for row in bills + notes})
        zone_by_bill = await self._bill_designated(tenant_id, bills)
        rcm_by_bill = {row.id: row.is_reverse_charge for row in bills}
        lines: list[TaxRegisterLine] = []
        for bill in bills:
            lines.append(
                self._purchase_register_line(
                    bill,
                    document_type="PURCHASE_INVOICE",
                    party_name=names.get(bill.supplier_id, ""),
                    party_trn=bill.supplier_trn or trns.get(bill.supplier_id),
                    taxes=taxes,
                    is_designated_zone=zone_by_bill.get(bill.id, False),
                    is_reverse_charge=bill.is_reverse_charge,
                    sign=Decimal("1"),
                )
            )
        for note in notes:
            reverse = False
            if note.purchase_invoice_id is not None:
                reverse = rcm_by_bill.get(note.purchase_invoice_id, False)
            lines.append(
                self._debit_register_line(
                    note,
                    party_name=names.get(note.supplier_id, ""),
                    party_trn=trns.get(note.supplier_id),
                    taxes=taxes,
                    is_reverse_charge=reverse,
                    sign=Decimal("-1"),
                )
            )
        if box:
            lines = [line for line in lines if self._line_matches_box(line, box)]
        return await self._register_response(tenant_id, from_date, to_date, lines)

    async def vat_201(
        self,
        tenant_id: UUID,
        *,
        from_date: date,
        to_date: date,
    ) -> Vat201Response:
        sales = await self.sales_register(tenant_id, from_date=from_date, to_date=to_date)
        purchases = await self.purchase_register(tenant_id, from_date=from_date, to_date=to_date)
        standard_net = _ZERO
        standard_vat = _ZERO
        zero_net = _ZERO
        exempt_net = _ZERO
        out_net = _ZERO
        for line in sales.lines:
            if line.is_designated_zone or line.tax_category == TaxCategory.OUT_OF_SCOPE.value:
                out_net += line.net_amount
            elif line.is_export or line.tax_category == TaxCategory.ZERO_RATED.value:
                zero_net += line.net_amount
            elif line.tax_category == TaxCategory.EXEMPT.value:
                exempt_net += line.net_amount
            else:
                standard_net += line.net_amount
                standard_vat += line.tax_amount
        rcm_net = _ZERO
        rcm_vat = _ZERO
        recoverable = _ZERO
        for line in purchases.lines:
            if line.is_reverse_charge:
                rcm_net += line.net_amount
                rcm_vat += line.tax_amount
                recoverable += line.tax_amount
            elif line.tax_category == TaxCategory.STANDARD.value:
                recoverable += line.tax_amount
        recoverable = quantize_money(recoverable)
        output = quantize_money(standard_vat + rcm_vat)
        net_vat = quantize_money(output - recoverable)
        exceptions = await self.export_evidence_exceptions(tenant_id, as_of=to_date)
        boxes = [
            Vat201Box(
                code="1a",
                label="Standard rated supplies",
                net_amount=quantize_money(standard_net),
                tax_amount=_ZERO,
            ),
            Vat201Box(
                code="1b",
                label="Standard rated output VAT",
                net_amount=_ZERO,
                tax_amount=quantize_money(standard_vat),
            ),
            Vat201Box(
                code="2",
                label="Zero rated supplies including exports",
                net_amount=quantize_money(zero_net),
                tax_amount=_ZERO,
            ),
            Vat201Box(
                code="3",
                label="Exempt supplies",
                net_amount=quantize_money(exempt_net),
                tax_amount=_ZERO,
            ),
            Vat201Box(
                code="4",
                label="Out of scope supplies including designated zones",
                net_amount=quantize_money(out_net),
                tax_amount=_ZERO,
            ),
            Vat201Box(
                code="5",
                label="Reverse charge supplies",
                net_amount=quantize_money(rcm_net),
                tax_amount=_ZERO,
            ),
            Vat201Box(
                code="6",
                label="Reverse charge output VAT",
                net_amount=_ZERO,
                tax_amount=quantize_money(rcm_vat),
            ),
            Vat201Box(
                code="7",
                label="Reverse charge input VAT",
                net_amount=_ZERO,
                tax_amount=quantize_money(rcm_vat),
            ),
            Vat201Box(
                code="8",
                label="Recoverable input VAT",
                net_amount=_ZERO,
                tax_amount=recoverable,
            ),
            Vat201Box(
                code="9",
                label="Net VAT payable / (refundable)",
                net_amount=_ZERO,
                tax_amount=net_vat,
            ),
        ]
        return Vat201Response(
            currency_code=await self._report_currency_code(tenant_id),
            from_date=from_date,
            to_date=to_date,
            boxes=boxes,
            recoverable_input_vat=recoverable,
            net_vat=net_vat,
            export_evidence_exceptions=len(exceptions.lines),
        )

    async def vat_gl_recon(
        self,
        tenant_id: UUID,
        *,
        from_date: date,
        to_date: date,
    ) -> VatGlReconResponse:
        vat = await self.vat_201(tenant_id, from_date=from_date, to_date=to_date)
        boxes = {box.code: box for box in vat.boxes}
        output_201 = quantize_money(
            (boxes.get("1b").tax_amount if boxes.get("1b") else _ZERO)
            + (boxes.get("6").tax_amount if boxes.get("6") else _ZERO)
        )
        input_201 = boxes.get("8").tax_amount if boxes.get("8") else _ZERO
        net_201 = boxes.get("9").tax_amount if boxes.get("9") else vat.net_vat
        output_account = await self.accounts.resolver.require(
            tenant_id, AccountSystemRole.VAT_OUTPUT
        )
        input_account = await self.accounts.resolver.require(
            tenant_id, AccountSystemRole.VAT_INPUT
        )
        output_map = await self._sum_by_account(
            tenant_id, start=from_date, end=to_date, account_id=output_account.id
        )
        input_map = await self._sum_by_account(
            tenant_id, start=from_date, end=to_date, account_id=input_account.id
        )
        output_d, output_c = output_map.get(output_account.id, (_ZERO, _ZERO))
        input_d, input_c = input_map.get(input_account.id, (_ZERO, _ZERO))
        gl_output = self._signed(output_account.account_type, output_d, output_c)
        gl_input = self._signed(input_account.account_type, input_d, input_c)
        gl_net = quantize_money(gl_output - gl_input)
        return VatGlReconResponse(
            currency_code=await self._report_currency_code(tenant_id),
            from_date=from_date,
            to_date=to_date,
            lines=[
                VatGlReconLine(
                    key="vat_output",
                    label="VAT output (boxes 1b + 6 vs VAT_OUTPUT GL)",
                    vat_201_amount=output_201,
                    gl_amount=gl_output,
                    difference=quantize_money(output_201 - gl_output),
                    account_id=output_account.id,
                ),
                VatGlReconLine(
                    key="vat_input",
                    label="Recoverable input VAT (box 8 vs VAT_INPUT GL)",
                    vat_201_amount=input_201,
                    gl_amount=gl_input,
                    difference=quantize_money(input_201 - gl_input),
                    account_id=input_account.id,
                ),
                VatGlReconLine(
                    key="net_vat",
                    label="Net VAT payable (box 9 vs output − input GL)",
                    vat_201_amount=net_201,
                    gl_amount=gl_net,
                    difference=quantize_money(net_201 - gl_net),
                ),
            ],
        )

    def _line_matches_box(self, line: TaxRegisterLine, box: str) -> bool:
        code = box.lower()
        if "export" in code or "zero" in code or code == "2":
            return line.is_export or line.tax_category == TaxCategory.ZERO_RATED.value
        if "exempt" in code or code == "3":
            return line.tax_category == TaxCategory.EXEMPT.value
        if "designated" in code or "out of scope" in code or "out_of_scope" in code or code == "4":
            return line.is_designated_zone or line.tax_category == TaxCategory.OUT_OF_SCOPE.value
        if "reverse" in code or "rcm" in code or code in {"5", "6", "7"}:
            return line.is_reverse_charge
        if "standard" in code or code in {"1a", "1b"}:
            return line.tax_category == TaxCategory.STANDARD.value or (
                not line.is_export and not line.is_reverse_charge
            )
        if code in {"8", "9"}:
            return True
        return True

    async def _register_response(
        self,
        tenant_id: UUID,
        from_date: date,
        to_date: date,
        lines: list[TaxRegisterLine],
    ) -> TaxRegisterResponse:
        return TaxRegisterResponse(
            currency_code=await self._report_currency_code(tenant_id),
            from_date=from_date,
            to_date=to_date,
            total_net=quantize_money(sum((line.net_amount for line in lines), _ZERO)),
            total_tax=quantize_money(sum((line.tax_amount for line in lines), _ZERO)),
            total_grand=quantize_money(sum((line.grand_total for line in lines), _ZERO)),
            lines=lines,
        )

    def _sales_register_line(
        self,
        invoice: SalesInvoice,
        *,
        document_type: str,
        party_name: str,
        party_trn: str | None,
        taxes: dict[UUID, Tax],
        is_designated_zone: bool,
        sign: Decimal,
    ) -> TaxRegisterLine:
        category = self._first_tax_category(invoice.lines, taxes)
        net_amount, tax_amount, grand_total = document_base_net_tax(invoice, sign=sign)
        return TaxRegisterLine(
            document_type=document_type,
            document_id=invoice.id,
            document_number=invoice.document_number,
            document_date=invoice.invoice_date,
            party_id=invoice.customer_id,
            party_name=party_name,
            party_trn=party_trn,
            tax_treatment=invoice.tax_treatment,
            tax_category=category,
            place_of_supply=invoice.place_of_supply,
            net_amount=net_amount,
            tax_amount=tax_amount,
            grand_total=grand_total,
            is_export=invoice.is_export,
            is_designated_zone=is_designated_zone,
        )

    def _credit_register_line(
        self,
        note: CreditNote,
        *,
        party_name: str,
        party_trn: str | None,
        taxes: dict[UUID, Tax],
        sign: Decimal,
    ) -> TaxRegisterLine:
        category = self._first_tax_category(note.lines, taxes)
        net_amount, tax_amount, grand_total = document_base_net_tax(note, sign=sign)
        return TaxRegisterLine(
            document_type="CREDIT_NOTE",
            document_id=note.id,
            document_number=note.document_number,
            document_date=note.credit_note_date,
            party_id=note.customer_id,
            party_name=party_name,
            party_trn=party_trn,
            tax_treatment=note.tax_treatment,
            tax_category=category,
            place_of_supply=note.place_of_supply,
            net_amount=net_amount,
            tax_amount=tax_amount,
            grand_total=grand_total,
            is_export=note.is_export,
        )

    def _purchase_register_line(
        self,
        bill: PurchaseInvoice,
        *,
        document_type: str,
        party_name: str,
        party_trn: str | None,
        taxes: dict[UUID, Tax],
        is_designated_zone: bool,
        is_reverse_charge: bool,
        sign: Decimal,
    ) -> TaxRegisterLine:
        category = self._first_tax_category(bill.lines, taxes)
        tax_src = bill.rcm_tax_amount if is_reverse_charge else bill.tax_amount
        net_amount, tax_amount, grand_total = document_base_net_tax(
            bill,
            sign=sign,
            net_amount=bill.rcm_taxable_amount if is_reverse_charge else None,
            tax_amount=tax_src,
        )
        return TaxRegisterLine(
            document_type=document_type,
            document_id=bill.id,
            document_number=bill.document_number,
            document_date=bill.invoice_date,
            party_id=bill.supplier_id,
            party_name=party_name,
            party_trn=party_trn,
            tax_treatment=bill.tax_treatment,
            tax_category=category,
            place_of_supply=bill.place_of_supply,
            net_amount=net_amount,
            tax_amount=tax_amount,
            grand_total=grand_total,
            is_reverse_charge=is_reverse_charge,
            is_designated_zone=is_designated_zone,
        )

    def _debit_register_line(
        self,
        note: DebitNote,
        *,
        party_name: str,
        party_trn: str | None,
        taxes: dict[UUID, Tax],
        is_reverse_charge: bool,
        sign: Decimal,
    ) -> TaxRegisterLine:
        category = self._first_tax_category(note.lines, taxes)
        net_amount, tax_amount, grand_total = document_base_net_tax(note, sign=sign)
        return TaxRegisterLine(
            document_type="DEBIT_NOTE",
            document_id=note.id,
            document_number=note.document_number,
            document_date=self._debit_note_date(note),
            party_id=note.supplier_id,
            party_name=party_name,
            party_trn=party_trn,
            tax_treatment=note.tax_treatment,
            tax_category=category,
            place_of_supply=note.place_of_supply,
            net_amount=net_amount,
            tax_amount=tax_amount,
            grand_total=grand_total,
            is_reverse_charge=is_reverse_charge,
        )

    @staticmethod
    def _debit_note_date(note: DebitNote) -> date:
        return note.debit_note_date

    @staticmethod
    def _first_tax_category(lines: list, taxes: dict[UUID, Tax]) -> str | None:
        for line in lines:
            tax_id = getattr(line, "tax_id", None)
            if tax_id is not None and tax_id in taxes:
                return taxes[tax_id].tax_category
        return None

    async def _posted_sales_invoices(
        self, tenant_id: UUID, from_date: date, to_date: date
    ) -> list[SalesInvoice]:
        statement = (
            select(SalesInvoice)
            .where(
                SalesInvoice.tenant_id == tenant_id,
                SalesInvoice.deleted_at.is_(None),
                SalesInvoice.status == InvoiceDocumentStatus.POSTED.value,
                SalesInvoice.invoice_date >= from_date,
                SalesInvoice.invoice_date <= to_date,
            )
            .options(selectinload(SalesInvoice.lines))
            .order_by(SalesInvoice.invoice_date, SalesInvoice.document_number)
        )
        return list((await self.session.execute(statement)).scalars().unique().all())

    async def _posted_credit_notes(
        self, tenant_id: UUID, from_date: date, to_date: date
    ) -> list[CreditNote]:
        statement = (
            select(CreditNote)
            .where(
                CreditNote.tenant_id == tenant_id,
                CreditNote.deleted_at.is_(None),
                CreditNote.status == InvoiceDocumentStatus.POSTED.value,
                CreditNote.credit_note_date >= from_date,
                CreditNote.credit_note_date <= to_date,
            )
            .options(selectinload(CreditNote.lines))
            .order_by(CreditNote.credit_note_date, CreditNote.document_number)
        )
        return list((await self.session.execute(statement)).scalars().unique().all())

    async def _posted_bills(
        self, tenant_id: UUID, from_date: date, to_date: date
    ) -> list[PurchaseInvoice]:
        statement = (
            select(PurchaseInvoice)
            .where(
                PurchaseInvoice.tenant_id == tenant_id,
                PurchaseInvoice.deleted_at.is_(None),
                PurchaseInvoice.status == InvoiceDocumentStatus.POSTED.value,
                PurchaseInvoice.invoice_date >= from_date,
                PurchaseInvoice.invoice_date <= to_date,
            )
            .options(selectinload(PurchaseInvoice.lines))
            .order_by(PurchaseInvoice.invoice_date, PurchaseInvoice.document_number)
        )
        return list((await self.session.execute(statement)).scalars().unique().all())

    async def _posted_debit_notes(
        self, tenant_id: UUID, from_date: date, to_date: date
    ) -> list[DebitNote]:
        statement = (
            select(DebitNote)
            .where(
                DebitNote.tenant_id == tenant_id,
                DebitNote.deleted_at.is_(None),
                DebitNote.status == InvoiceDocumentStatus.POSTED.value,
                DebitNote.debit_note_date >= from_date,
                DebitNote.debit_note_date <= to_date,
            )
            .options(selectinload(DebitNote.lines))
            .order_by(DebitNote.debit_note_date, DebitNote.document_number)
        )
        return list((await self.session.execute(statement)).scalars().unique().all())

    async def _taxes(self, tenant_id: UUID) -> dict[UUID, Tax]:
        rows = (
            (
                await self.session.execute(
                    select(Tax).where(Tax.tenant_id == tenant_id, Tax.deleted_at.is_(None))
                )
            )
            .scalars()
            .all()
        )
        return {row.id: row for row in rows}

    async def _party_names(
        self, tenant_id: UUID, ids: set[UUID]
    ) -> tuple[dict[UUID, str], dict[UUID, str | None]]:
        if not ids:
            return {}, {}
        rows = (
            await self.session.execute(
                select(Customer.id, Customer.name, Customer.trn).where(
                    Customer.tenant_id == tenant_id, Customer.id.in_(list(ids))
                )
            )
        ).all()
        names = {row[0]: row[1] for row in rows}
        trns = {row[0]: row[2] for row in rows}
        return names, trns

    async def _invoice_designated(
        self, tenant_id: UUID, invoices: list[SalesInvoice]
    ) -> dict[UUID, bool]:
        dn_ids: set[UUID] = set()
        so_ids: set[UUID] = set()
        for invoice in invoices:
            if invoice.sales_order_id is not None:
                so_ids.add(invoice.sales_order_id)
            for line in invoice.lines:
                if line.delivery_note_id is not None:
                    dn_ids.add(line.delivery_note_id)
        warehouse_ids: set[UUID] = set()
        dn_warehouse: dict[UUID, UUID] = {}
        if dn_ids:
            notes = (
                await self.session.execute(
                    select(DeliveryNote.id, DeliveryNote.warehouse_id).where(
                        DeliveryNote.tenant_id == tenant_id,
                        DeliveryNote.id.in_(list(dn_ids)),
                    )
                )
            ).all()
            for note_id, warehouse_id in notes:
                dn_warehouse[note_id] = warehouse_id
                warehouse_ids.add(warehouse_id)
        so_warehouse: dict[UUID, UUID] = {}
        if so_ids:
            from app.erp.sales_orders.models import SalesOrder

            orders = (
                await self.session.execute(
                    select(SalesOrder.id, SalesOrder.warehouse_id).where(
                        SalesOrder.tenant_id == tenant_id,
                        SalesOrder.id.in_(list(so_ids)),
                    )
                )
            ).all()
            for order_id, warehouse_id in orders:
                if warehouse_id is not None:
                    so_warehouse[order_id] = warehouse_id
                    warehouse_ids.add(warehouse_id)
        flags = await self._warehouse_flags(tenant_id, warehouse_ids)
        result: dict[UUID, bool] = {}
        for invoice in invoices:
            designated = False
            for line in invoice.lines:
                warehouse_id = (
                    dn_warehouse.get(line.delivery_note_id) if line.delivery_note_id else None
                )
                if warehouse_id is not None and flags.get(warehouse_id):
                    designated = True
                    break
            if not designated and invoice.sales_order_id is not None:
                warehouse_id = so_warehouse.get(invoice.sales_order_id)
                designated = bool(warehouse_id and flags.get(warehouse_id))
            result[invoice.id] = designated
        return result

    async def _bill_designated(
        self, tenant_id: UUID, bills: list[PurchaseInvoice]
    ) -> dict[UUID, bool]:
        receipt_ids = {bill.goods_receipt_id for bill in bills if bill.goods_receipt_id is not None}
        for bill in bills:
            for line in bill.lines:
                if line.goods_receipt_id is not None:
                    receipt_ids.add(line.goods_receipt_id)
        if not receipt_ids:
            return {bill.id: False for bill in bills}
        receipts = (
            await self.session.execute(
                select(GoodsReceipt.id, GoodsReceipt.warehouse_id).where(
                    GoodsReceipt.tenant_id == tenant_id,
                    GoodsReceipt.id.in_(list(receipt_ids)),
                )
            )
        ).all()
        receipt_warehouse = {row[0]: row[1] for row in receipts}
        flags = await self._warehouse_flags(tenant_id, set(receipt_warehouse.values()))
        result: dict[UUID, bool] = {}
        for bill in bills:
            warehouse_id = None
            if bill.goods_receipt_id is not None:
                warehouse_id = receipt_warehouse.get(bill.goods_receipt_id)
            if warehouse_id is None:
                for line in bill.lines:
                    if line.goods_receipt_id is not None:
                        warehouse_id = receipt_warehouse.get(line.goods_receipt_id)
                        if warehouse_id is not None:
                            break
            result[bill.id] = bool(warehouse_id and flags.get(warehouse_id))
        return result

    async def _warehouse_flags(self, tenant_id: UUID, warehouse_ids: set[UUID]) -> dict[UUID, bool]:
        if not warehouse_ids:
            return {}
        rows = (
            await self.session.execute(
                select(Warehouse.id, Warehouse.is_designated_zone).where(
                    Warehouse.tenant_id == tenant_id,
                    Warehouse.id.in_(list(warehouse_ids)),
                )
            )
        ).all()
        return {row[0]: bool(row[1]) for row in rows}

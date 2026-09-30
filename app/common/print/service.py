"""Build print letterhead from tenant settings. Never hard-code company constants."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.org_service import OrganizationService
from app.common.print.schemas import (
    PrintDocumentResponse,
    PrintJournalLine,
    PrintLetterhead,
    PrintLine,
)
from app.common.utils.money_words import amount_in_words


class PrintService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.org = OrganizationService(session)

    async def letterhead(self, tenant_id: UUID) -> PrintLetterhead:
        current = await self.org.get_current_tenant(tenant_id)
        address = None
        if current.headquarters is not None:
            hq = current.headquarters
            parts = [
                hq.address_line_1,
                hq.address_line_2,
                hq.city,
                hq.state,
                hq.postal_code,
                hq.country,
            ]
            address = ", ".join(part for part in parts if part) or None
        return PrintLetterhead(
            company_name=current.name,
            company_code=current.code,
            trn=await self.org.get_trn(tenant_id),
            phone=current.phone,
            email=current.contact_email,
            website=current.website,
            address=address,
            logo_url=current.logo_url,
            bank_details=await self.org.get_bank_details(tenant_id),
            default_currency=current.default_currency,
        )

    async def assemble(
        self,
        tenant_id: UUID,
        *,
        document_type: str,
        document_id: UUID,
        document_number: str,
        document_date: date,
        template_family: str = "uae",
        customer_code: str | None = None,
        customer_name: str | None = None,
        customer_address: str | None = None,
        customer_trn: str | None = None,
        lpo_number: str | None = None,
        delivery_note_number: str | None = None,
        invoice_number: str | None = None,
        bl_number: str | None = None,
        container_number: str | None = None,
        incoterm: str | None = None,
        incoterm_place: str | None = None,
        currency_code: str | None = None,
        subtotal: Decimal | None = None,
        tax_amount: Decimal | None = None,
        grand_total: Decimal | None = None,
        payment_terms: str | None = None,
        notes: str | None = None,
        lines: list[PrintLine] | None = None,
    ) -> PrintDocumentResponse:
        letterhead = await self.letterhead(tenant_id)
        return PrintDocumentResponse(
            document_type=document_type,
            document_id=document_id,
            document_number=document_number,
            document_date=document_date,
            template_family=template_family,
            customer_code=customer_code,
            customer_name=customer_name,
            customer_address=customer_address,
            customer_trn=customer_trn,
            lpo_number=lpo_number,
            delivery_note_number=delivery_note_number,
            invoice_number=invoice_number,
            bl_number=bl_number,
            container_number=container_number,
            incoterm=incoterm,
            incoterm_place=incoterm_place,
            currency_code=currency_code,
            subtotal=subtotal,
            tax_amount=tax_amount,
            grand_total=grand_total,
            amount_in_words=self.words(grand_total, currency=currency_code),
            payment_terms=payment_terms,
            notes=notes,
            letterhead=letterhead,
            lines=lines or [],
        )

    @staticmethod
    def commercial_line(line: Any, *, index: int) -> PrintLine:
        amount = getattr(line, "amount", None)
        rate = getattr(line, "rate", None)
        return PrintLine(
            line_number=getattr(line, "line_number", index),
            item_code=getattr(line, "item_code", None),
            description=getattr(line, "description", "") or "",
            packing_unit=getattr(line, "packing_unit", None),
            carton_qty=getattr(line, "carton_qty", None),
            quantity=line.quantity,
            unit_price=rate,
            taxable_amount=amount,
            tax_rate=getattr(line, "tax_rate", None),
            tax_amount=getattr(line, "tax_amount", None),
            amount=amount,
            cbm=getattr(line, "cbm", None),
            weight=getattr(line, "weight", None),
        )

    @staticmethod
    def words(amount: Decimal | None, *, currency: str | None) -> str | None:
        if amount is None:
            return None
        return amount_in_words(amount, currency_code=currency)

    async def assemble_voucher(
        self,
        tenant_id: UUID,
        *,
        document_type: str,
        document_id: UUID,
        document_number: str,
        document_date: date,
        voucher_type: str,
        template_family: str = "uae",
        currency_code: str | None = None,
        total_amount: Decimal,
        payment_method: str | None = None,
        party_name: str | None = None,
        party_code: str | None = None,
        cheque_number: str | None = None,
        cheque_date: date | None = None,
        narration: str | None = None,
        reference: str | None = None,
        journal_lines: list[PrintJournalLine],
    ) -> PrintDocumentResponse:
        template_kind = "journal" if voucher_type == "JOURNAL" else "voucher"
        return await self._assemble_accounting(
            tenant_id,
            document_type=document_type,
            document_id=document_id,
            document_number=document_number,
            document_date=document_date,
            template_family=template_family,
            template_kind=template_kind,
            voucher_type=voucher_type,
            currency_code=currency_code,
            total_amount=total_amount,
            payment_method=payment_method,
            party_name=party_name,
            party_code=party_code,
            cheque_number=cheque_number,
            cheque_date=cheque_date,
            narration=narration,
            reference=reference,
            journal_lines=journal_lines,
        )

    async def assemble_cheque(
        self,
        tenant_id: UUID,
        *,
        document_id: UUID,
        document_number: str,
        document_date: date,
        template_family: str = "uae",
        currency_code: str | None = None,
        amount: Decimal,
        cheque_number: str,
        due_date: date | None = None,
        direction: str,
        party_name: str | None = None,
        party_code: str | None = None,
        bank_name: str | None = None,
        narration: str | None = None,
    ) -> PrintDocumentResponse:
        return await self._assemble_accounting(
            tenant_id,
            document_type="CHEQUE",
            document_id=document_id,
            document_number=document_number,
            document_date=document_date,
            template_family=template_family,
            template_kind="cheque",
            currency_code=currency_code,
            total_amount=amount,
            cheque_number=cheque_number,
            cheque_date=document_date,
            due_date=due_date,
            narration=narration or f"{direction.title()} cheque {cheque_number}",
            reference=bank_name,
            journal_lines=[],
        )

    async def _assemble_accounting(
        self,
        tenant_id: UUID,
        *,
        document_type: str,
        document_id: UUID,
        document_number: str,
        document_date: date,
        template_family: str,
        template_kind: str,
        currency_code: str | None,
        total_amount: Decimal,
        voucher_type: str | None = None,
        payment_method: str | None = None,
        party_name: str | None = None,
        party_code: str | None = None,
        cheque_number: str | None = None,
        cheque_date: date | None = None,
        due_date: date | None = None,
        narration: str | None = None,
        reference: str | None = None,
        journal_lines: list[PrintJournalLine],
    ) -> PrintDocumentResponse:
        letterhead = await self.letterhead(tenant_id)
        family = template_family if template_family in {"uae", "china"} else "uae"
        return PrintDocumentResponse(
            document_type=document_type,
            document_id=document_id,
            document_number=document_number,
            document_date=document_date,
            template_family=family,
            template_kind=template_kind,
            voucher_type=voucher_type,
            payment_method=payment_method,
            party_name=party_name,
            party_code=party_code,
            cheque_number=cheque_number,
            cheque_date=cheque_date,
            due_date=due_date,
            narration=narration,
            reference=reference,
            currency_code=currency_code,
            grand_total=total_amount,
            amount_in_words=self.words(total_amount, currency=currency_code),
            notes=narration,
            letterhead=letterhead,
            journal_lines=journal_lines,
        )

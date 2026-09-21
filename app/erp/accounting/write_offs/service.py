"""Write off open AR/AP balances without reversing revenue or VAT."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import PERIOD_OVERRIDE, WRITE_OFF_CREATE, WRITE_OFF_REVERSE
from app.auth.org_service import OrganizationService
from app.common.idempotency.service import IdempotencyService
from app.common.utils.currency import quantize_money
from app.common.utils.datetime import utcnow
from app.core.enums import (
    AccountSystemRole,
    InvoiceDocumentStatus,
    JournalType,
    PartyType,
)
from app.core.exceptions import DocumentStaleError, ResourceNotFoundError, ValidationError
from app.core.permissions import has_permission
from app.db.session import transaction
from app.erp.accounting.accounts.models import Account
from app.erp.accounting.accounts.service import AccountResolver, AccountService
from app.erp.accounting.ledger.posting import LedgerPostingService
from app.erp.accounting.ledger.schemas import JournalLineInput
from app.erp.accounting.write_offs.constants import (
    DOCUMENT_KIND_PURCHASE_INVOICE,
    DOCUMENT_KIND_SALES_INVOICE,
    SOURCE_PURCHASE_INVOICE_WRITE_OFF,
    SOURCE_SALES_INVOICE_WRITE_OFF,
)
from app.erp.accounting.write_offs.repository import InvoiceWriteOffRepository
from app.erp.accounting.write_offs.schemas import (
    InvoiceWriteOffRequest,
    InvoiceWriteOffReverseRequest,
)
from app.erp.purchase_invoices.models import PurchaseInvoice
from app.erp.purchase_invoices.repository import PurchaseInvoiceRepository
from app.erp.purchase_invoices.schemas import PurchaseInvoiceResponse
from app.erp.purchase_invoices.service import PurchaseInvoiceService
from app.erp.sales_invoices.models import SalesInvoice
from app.erp.sales_invoices.repository import SalesInvoiceRepository
from app.erp.sales_invoices.schemas import SalesInvoiceResponse
from app.erp.sales_invoices.service import SalesInvoiceService

_ZERO = Decimal("0")


class InvoiceWriteOffService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] | set[str] | None = None,
    ) -> None:
        self.session = session
        self.actor_permissions = frozenset(actor_permissions or ())
        self.repo = InvoiceWriteOffRepository(session)
        self.sales_invoices = SalesInvoiceRepository(session)
        self.purchase_invoices = PurchaseInvoiceRepository(session)
        self.accounts = AccountService(session)
        self.resolver = AccountResolver(session)
        self.posting = LedgerPostingService(session, actor_permissions=self.actor_permissions)
        self.org = OrganizationService(session)
        self.idempotency = IdempotencyService(session)

    @property
    def _can_override(self) -> bool:
        return has_permission(self.actor_permissions, PERIOD_OVERRIDE)

    async def write_off_sales_invoice(
        self,
        tenant_id: UUID,
        invoice_id: UUID,
        payload: InvoiceWriteOffRequest,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> tuple[SalesInvoiceResponse, UUID]:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                meta = replay.get("meta") or {}
                write_off_id = meta.get("write_off_id")
                if write_off_id is None:
                    raise ValidationError("Idempotent replay is missing write-off metadata")
                invoice_payload = {key: value for key, value in replay.items() if key != "meta"}
                parsed = SalesInvoiceResponse.model_validate(invoice_payload)
                return parsed, UUID(str(write_off_id))
            row = await self._require_sales(tenant_id, invoice_id, for_update=True)
            self._assert_sales_version(row, expected_version)
            response, write_off_id = await self._write_off_sales(
                tenant_id, row, payload, actor_user_id=actor_user_id
            )
            await self.idempotency.store(
                tenant_id,
                idempotency_key,
                {
                    **response.model_dump(mode="json"),
                    "meta": {"write_off_id": str(write_off_id)},
                },
            )
            return response, write_off_id

    async def reverse_sales_write_off(
        self,
        tenant_id: UUID,
        invoice_id: UUID,
        payload: InvoiceWriteOffReverseRequest,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> SalesInvoiceResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return SalesInvoiceResponse.model_validate(replay)
            row = await self._require_sales(tenant_id, invoice_id, for_update=True)
            self._assert_sales_version(row, expected_version)
            response = await self._reverse_sales(
                tenant_id, row, payload, actor_user_id=actor_user_id
            )
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def write_off_purchase_invoice(
        self,
        tenant_id: UUID,
        invoice_id: UUID,
        payload: InvoiceWriteOffRequest,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> tuple[PurchaseInvoiceResponse, UUID]:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                meta = replay.get("meta") or {}
                write_off_id = meta.get("write_off_id")
                if write_off_id is None:
                    raise ValidationError("Idempotent replay is missing write-off metadata")
                invoice_payload = {key: value for key, value in replay.items() if key != "meta"}
                parsed = PurchaseInvoiceResponse.model_validate(invoice_payload)
                return parsed, UUID(str(write_off_id))
            row = await self._require_purchase(tenant_id, invoice_id, for_update=True)
            self._assert_purchase_version(row, expected_version)
            response, write_off_id = await self._write_off_purchase(
                tenant_id, row, payload, actor_user_id=actor_user_id
            )
            await self.idempotency.store(
                tenant_id,
                idempotency_key,
                {
                    **response.model_dump(mode="json"),
                    "meta": {"write_off_id": str(write_off_id)},
                },
            )
            return response, write_off_id

    async def reverse_purchase_write_off(
        self,
        tenant_id: UUID,
        invoice_id: UUID,
        payload: InvoiceWriteOffReverseRequest,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> PurchaseInvoiceResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return PurchaseInvoiceResponse.model_validate(replay)
            row = await self._require_purchase(tenant_id, invoice_id, for_update=True)
            self._assert_purchase_version(row, expected_version)
            response = await self._reverse_purchase(
                tenant_id, row, payload, actor_user_id=actor_user_id
            )
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def _write_off_sales(
        self,
        tenant_id: UUID,
        row: SalesInvoice,
        payload: InvoiceWriteOffRequest,
        *,
        actor_user_id: UUID,
    ) -> tuple[SalesInvoiceResponse, UUID]:
        if not has_permission(self.actor_permissions, WRITE_OFF_CREATE):
            raise ValidationError("Missing permission to write off invoices")
        self._assert_posted_sales(row)
        amount = quantize_money(payload.amount)
        await self._assert_period_open(tenant_id, payload.write_off_date)
        if amount <= _ZERO or amount > row.balance_due:
            raise ValidationError("Write-off amount must be positive and within balance due")
        expense = await self._resolve_expense_account(tenant_id, payload.expense_account_id)
        ar = await self.accounts.party_resolver.resolve_receivable(tenant_id, row.customer_id)
        write_off = await self.repo.create(
            tenant_id,
            {
                "document_kind": DOCUMENT_KIND_SALES_INVOICE,
                "invoice_id": row.id,
                "amount": amount,
                "write_off_date": payload.write_off_date,
                "reason": payload.reason,
                "expense_account_id": expense.id,
                "created_by": actor_user_id,
                "updated_by": actor_user_id,
            },
        )
        journal = await self.posting.post_for_document(
            tenant_id,
            source_type=SOURCE_SALES_INVOICE_WRITE_OFF,
            source_id=write_off.id,
            entry_date=payload.write_off_date,
            lines=[
                JournalLineInput(
                    account_id=expense.id,
                    debit=amount,
                    description=f"Bad debt write-off {row.document_number}",
                ),
                JournalLineInput(
                    account_id=ar.id,
                    credit=amount,
                    party_type=PartyType.CUSTOMER,
                    party_id=row.customer_id,
                    due_date=row.due_date,
                    external_reference=row.document_number,
                    description=f"AR write-off {row.document_number}",
                ),
            ],
            currency_id=row.currency_id,
            exchange_rate=row.exchange_rate,
            narration=payload.reason or f"Write off sales invoice {row.document_number}",
            branch_id=row.branch_id,
            actor_id=actor_user_id,
            journal_type=JournalType.SYSTEM,
            reference=row.document_number,
        )
        write_off.journal_entry_id = journal.id
        row.amount_written_off = quantize_money(row.amount_written_off + amount)
        row.version += 1
        row.updated_by = actor_user_id
        sales_svc = SalesInvoiceService(self.session, actor_permissions=self.actor_permissions)
        sales_svc._refresh_payment_status(row)
        await self.session.flush()
        loaded = await sales_svc._require(tenant_id, row.id)
        return sales_svc._to_response(loaded), write_off.id

    async def _reverse_sales(
        self,
        tenant_id: UUID,
        row: SalesInvoice,
        payload: InvoiceWriteOffReverseRequest,
        *,
        actor_user_id: UUID,
    ) -> SalesInvoiceResponse:
        if not has_permission(self.actor_permissions, WRITE_OFF_REVERSE):
            raise ValidationError("Missing permission to reverse write-offs")
        self._assert_posted_sales(row)
        write_off = await self.repo.get(tenant_id, payload.write_off_id, for_update=True)
        if write_off is None or write_off.invoice_id != row.id:
            raise ResourceNotFoundError("Write-off not found")
        if write_off.document_kind != DOCUMENT_KIND_SALES_INVOICE:
            raise ValidationError("Write-off does not belong to this sales invoice")
        if write_off.reversed_at is not None:
            raise ValidationError("Write-off is already reversed")
        if write_off.journal_entry_id is None:
            raise ValidationError("Write-off has no posted journal")
        await self._assert_period_open(tenant_id, payload.reversal_date)
        reversal = await self.posting.reverse(
            tenant_id,
            write_off.journal_entry_id,
            reversal_date=payload.reversal_date,
            reason=payload.reason,
            actor_id=actor_user_id,
        )
        write_off.reversal_journal_entry_id = reversal.id
        write_off.reversed_at = utcnow()
        write_off.updated_by = actor_user_id
        row.amount_written_off = quantize_money(row.amount_written_off - write_off.amount)
        if row.amount_written_off < _ZERO:
            raise ValidationError("Written-off amount cannot be negative")
        row.version += 1
        row.updated_by = actor_user_id
        sales_svc = SalesInvoiceService(self.session, actor_permissions=self.actor_permissions)
        sales_svc._refresh_payment_status(row)
        await self.session.flush()
        loaded = await sales_svc._require(tenant_id, row.id)
        return sales_svc._to_response(loaded)

    async def _write_off_purchase(
        self,
        tenant_id: UUID,
        row: PurchaseInvoice,
        payload: InvoiceWriteOffRequest,
        *,
        actor_user_id: UUID,
    ) -> tuple[PurchaseInvoiceResponse, UUID]:
        if not has_permission(self.actor_permissions, WRITE_OFF_CREATE):
            raise ValidationError("Missing permission to write off invoices")
        self._assert_posted_purchase(row)
        amount = quantize_money(payload.amount)
        await self._assert_period_open(tenant_id, payload.write_off_date)
        if amount <= _ZERO or amount > row.balance_due:
            raise ValidationError("Write-off amount must be positive and within balance due")
        expense = await self._resolve_expense_account(tenant_id, payload.expense_account_id)
        ap = await self.accounts.party_resolver.resolve_payable(tenant_id, row.supplier_id)
        write_off = await self.repo.create(
            tenant_id,
            {
                "document_kind": DOCUMENT_KIND_PURCHASE_INVOICE,
                "invoice_id": row.id,
                "amount": amount,
                "write_off_date": payload.write_off_date,
                "reason": payload.reason,
                "expense_account_id": expense.id,
                "created_by": actor_user_id,
                "updated_by": actor_user_id,
            },
        )
        journal = await self.posting.post_for_document(
            tenant_id,
            source_type=SOURCE_PURCHASE_INVOICE_WRITE_OFF,
            source_id=write_off.id,
            entry_date=payload.write_off_date,
            lines=[
                JournalLineInput(
                    account_id=ap.id,
                    debit=amount,
                    party_type=PartyType.SUPPLIER,
                    party_id=row.supplier_id,
                    due_date=row.due_date,
                    external_reference=row.document_number,
                    description=f"AP write-off {row.document_number}",
                ),
                JournalLineInput(
                    account_id=expense.id,
                    credit=amount,
                    description=f"Bill write-off {row.document_number}",
                ),
            ],
            currency_id=row.currency_id,
            exchange_rate=row.exchange_rate,
            narration=payload.reason or f"Write off purchase invoice {row.document_number}",
            branch_id=row.branch_id,
            actor_id=actor_user_id,
            journal_type=JournalType.SYSTEM,
            reference=row.document_number,
        )
        write_off.journal_entry_id = journal.id
        row.amount_written_off = quantize_money(row.amount_written_off + amount)
        row.version += 1
        row.updated_by = actor_user_id
        purchase_svc = PurchaseInvoiceService(
            self.session, actor_permissions=self.actor_permissions
        )
        purchase_svc._refresh_payment_status(row)
        await self.session.flush()
        loaded = await purchase_svc._require(tenant_id, row.id)
        return purchase_svc._to_response(loaded), write_off.id

    async def _reverse_purchase(
        self,
        tenant_id: UUID,
        row: PurchaseInvoice,
        payload: InvoiceWriteOffReverseRequest,
        *,
        actor_user_id: UUID,
    ) -> PurchaseInvoiceResponse:
        if not has_permission(self.actor_permissions, WRITE_OFF_REVERSE):
            raise ValidationError("Missing permission to reverse write-offs")
        self._assert_posted_purchase(row)
        write_off = await self.repo.get(tenant_id, payload.write_off_id, for_update=True)
        if write_off is None or write_off.invoice_id != row.id:
            raise ResourceNotFoundError("Write-off not found")
        if write_off.document_kind != DOCUMENT_KIND_PURCHASE_INVOICE:
            raise ValidationError("Write-off does not belong to this purchase invoice")
        if write_off.reversed_at is not None:
            raise ValidationError("Write-off is already reversed")
        if write_off.journal_entry_id is None:
            raise ValidationError("Write-off has no posted journal")
        await self._assert_period_open(tenant_id, payload.reversal_date)
        reversal = await self.posting.reverse(
            tenant_id,
            write_off.journal_entry_id,
            reversal_date=payload.reversal_date,
            reason=payload.reason,
            actor_id=actor_user_id,
        )
        write_off.reversal_journal_entry_id = reversal.id
        write_off.reversed_at = utcnow()
        write_off.updated_by = actor_user_id
        row.amount_written_off = quantize_money(row.amount_written_off - write_off.amount)
        if row.amount_written_off < _ZERO:
            raise ValidationError("Written-off amount cannot be negative")
        row.version += 1
        row.updated_by = actor_user_id
        purchase_svc = PurchaseInvoiceService(
            self.session, actor_permissions=self.actor_permissions
        )
        purchase_svc._refresh_payment_status(row)
        await self.session.flush()
        loaded = await purchase_svc._require(tenant_id, row.id)
        return purchase_svc._to_response(loaded)

    async def _resolve_expense_account(
        self, tenant_id: UUID, override_id: UUID | None
    ) -> Account:
        if override_id is not None:
            return await self.accounts.require_postable(tenant_id, override_id)
        return await self.resolver.require(tenant_id, AccountSystemRole.BAD_DEBT_EXPENSE)

    async def _assert_period_open(self, tenant_id: UUID, entry_date: date) -> None:
        _, policy = await self.org.get_inventory_controls(tenant_id)
        policy.assert_open(entry_date, can_override=self._can_override)

    async def _require_sales(
        self, tenant_id: UUID, invoice_id: UUID, *, for_update: bool
    ) -> SalesInvoice:
        row = await self.sales_invoices.get(tenant_id, invoice_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Sales invoice not found")
        return row

    async def _require_purchase(
        self, tenant_id: UUID, invoice_id: UUID, *, for_update: bool
    ) -> PurchaseInvoice:
        row = await self.purchase_invoices.get(tenant_id, invoice_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Purchase invoice not found")
        return row

    @staticmethod
    def _assert_sales_version(row: SalesInvoice, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError()

    @staticmethod
    def _assert_purchase_version(row: PurchaseInvoice, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError()

    @staticmethod
    def _assert_posted_sales(row: SalesInvoice) -> None:
        if InvoiceDocumentStatus(row.status) != InvoiceDocumentStatus.POSTED:
            raise ValidationError("Only posted sales invoices can be written off")

    @staticmethod
    def _assert_posted_purchase(row: PurchaseInvoice) -> None:
        if InvoiceDocumentStatus(row.status) != InvoiceDocumentStatus.POSTED:
            raise ValidationError("Only posted purchase invoices can be written off")

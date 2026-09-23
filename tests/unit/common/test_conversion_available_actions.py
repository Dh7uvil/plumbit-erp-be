"""Unit tests: cross-conversion actions are exposed from backend state."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.auth.catalog import (
    COST_SHEET_CREATE,
    CREDIT_NOTE_CREATE,
    CUSTOMER_PAYMENT_CREATE,
    DEBIT_NOTE_CREATE,
    DELIVERY_NOTE_CREATE,
    DELIVERY_NOTE_DELETE,
    GOODS_RECEIPT_CREATE,
    GOODS_RECEIPT_DELETE,
    LANDED_COST_CREATE,
    PURCHASE_INVOICE_CREATE,
    SALES_INVOICE_CREATE,
    SALES_RETURN_CREATE,
    SHIPMENT_UPDATE,
    SUPPLIER_PAYMENT_CREATE,
)
from app.core.enums import (
    BillingStatus,
    InvoiceDocumentStatus,
    ProformaInvoiceStatus,
    PurchaseOrderStatus,
    ReceiptStatus,
    SalesOrderStatus,
    ShipmentStatus,
    StockDocumentStatus,
)
from app.erp.purchase_orders.models import PurchaseOrder
from app.erp.purchase_orders.service import PurchaseOrderService
from app.erp.sales_orders.models import SalesOrder, SalesOrderLine
from app.erp.sales_orders.service import SalesOrderService
from app.erp.credit_notes.models import CreditNote
from app.erp.credit_notes.service import CreditNoteService
from app.erp.debit_notes.models import DebitNote
from app.erp.debit_notes.service import DebitNoteService
from app.erp.purchase_invoices.models import PurchaseInvoice, PurchaseInvoiceLine
from app.erp.purchase_invoices.service import PurchaseInvoiceService
from app.erp.sales_invoices.models import SalesInvoice, SalesInvoiceLine
from app.erp.sales_invoices.service import SalesInvoiceService
from app.inventory_management.delivery_notes.models import DeliveryNote
from app.inventory_management.delivery_notes.service import DeliveryNoteService
from app.inventory_management.goods_receipts.models import GoodsReceipt, GoodsReceiptLine
from app.inventory_management.goods_receipts.service import GoodsReceiptService
from app.inventory_management.sales_returns.service import SalesReturnService
from app.erp.proforma_invoices.service import ProformaInvoiceService
from app.logistics.shipments.service import ShipmentService


def _actions_service(service_cls, permissions: frozenset[str]):
    service = service_cls.__new__(service_cls)
    service.actor_permissions = permissions
    return service


def test_confirmed_sales_order_exposes_conversion_actions() -> None:
    tenant_id = uuid4()
    row = SalesOrder(
        tenant_id=tenant_id,
        document_number="SO-00001",
        status=SalesOrderStatus.CONFIRMED.value,
        billing_status=BillingStatus.NOT_INVOICED.value,
        version=1,
        customer_id=uuid4(),
        currency_id=uuid4(),
        base_currency_id=uuid4(),
        exchange_rate=Decimal("1"),
        tax_treatment="STANDARD",
        place_of_supply="UAE",
        grand_total=Decimal("100"),
        base_amount=Decimal("100"),
    )
    row.id = uuid4()
    line = SalesOrderLine(
        tenant_id=tenant_id,
        sales_order_id=row.id,
        line_number=1,
        description="Widget",
        quantity=Decimal("10"),
        qty_delivered=Decimal("0"),
        qty_invoiced=Decimal("0"),
        rate=Decimal("10"),
    )
    line.id = uuid4()
    row.lines = [line]

    service = _actions_service(
        SalesOrderService,
        frozenset({CUSTOMER_PAYMENT_CREATE, SALES_INVOICE_CREATE}),
    )
    actions = service._available_actions(row, requires_approval=False)

    assert "record_advance" in actions
    assert "create_sales_invoice" in actions


def test_draft_purchase_order_hides_pay_advance_and_cost_sheet() -> None:
    row = PurchaseOrder(
        tenant_id=uuid4(),
        document_number="PO-00002",
        status=PurchaseOrderStatus.DRAFT.value,
        receipt_status=ReceiptStatus.NOT_RECEIVED.value,
        billing_status=BillingStatus.NOT_INVOICED.value,
        version=1,
        supplier_id=uuid4(),
        currency_id=uuid4(),
        base_currency_id=uuid4(),
        exchange_rate=Decimal("1"),
        tax_treatment="STANDARD",
        place_of_supply="UAE",
        grand_total=Decimal("100"),
        base_amount=Decimal("100"),
    )
    row.id = uuid4()

    service = _actions_service(
        PurchaseOrderService,
        frozenset(
            {SUPPLIER_PAYMENT_CREATE, PURCHASE_INVOICE_CREATE, COST_SHEET_CREATE},
        ),
    )
    actions = service._available_actions(
        row, PurchaseOrderStatus.DRAFT, requires_approval=False
    )

    assert "pay_advance" not in actions
    assert "create_cost_sheet" not in actions


def test_issued_purchase_order_exposes_pay_and_bill_actions() -> None:
    row = PurchaseOrder(
        tenant_id=uuid4(),
        document_number="PO-00001",
        status=PurchaseOrderStatus.ISSUED.value,
        receipt_status=ReceiptStatus.NOT_RECEIVED.value,
        billing_status=BillingStatus.NOT_INVOICED.value,
        version=1,
        supplier_id=uuid4(),
        currency_id=uuid4(),
        base_currency_id=uuid4(),
        exchange_rate=Decimal("1"),
        tax_treatment="STANDARD",
        place_of_supply="UAE",
        grand_total=Decimal("100"),
        base_amount=Decimal("100"),
    )
    row.id = uuid4()

    service = _actions_service(
        PurchaseOrderService,
        frozenset(
            {SUPPLIER_PAYMENT_CREATE, PURCHASE_INVOICE_CREATE, COST_SHEET_CREATE},
        ),
    )
    actions = service._available_actions(
        row, PurchaseOrderStatus.ISSUED, requires_approval=False
    )

    assert "pay_advance" in actions
    assert "create_bill" in actions
    assert "create_cost_sheet" in actions


def test_posted_delivery_note_exposes_downstream_actions() -> None:
    row = DeliveryNote(
        tenant_id=uuid4(),
        document_number="DN-00001",
        status=StockDocumentStatus.POSTED.value,
        version=1,
        document_date=date.today(),
        sales_order_id=uuid4(),
        customer_id=uuid4(),
        warehouse_id=uuid4(),
        tax_treatment="STANDARD",
        place_of_supply="UAE",
        shipment_id=None,
    )
    row.id = uuid4()

    service = _actions_service(
        DeliveryNoteService,
        frozenset(
            {SALES_RETURN_CREATE, SALES_INVOICE_CREATE, SHIPMENT_UPDATE, DELIVERY_NOTE_DELETE},
        ),
    )
    actions = service._available_actions(row, StockDocumentStatus.POSTED, period_locked=False)

    assert "create_return" in actions
    assert "create_sales_invoice" in actions
    assert "add_to_shipment" in actions


def test_invoice_sourced_delivery_note_exposes_create_return_without_sales_order() -> None:
    row = DeliveryNote(
        tenant_id=uuid4(),
        document_number="DN-00002",
        status=StockDocumentStatus.POSTED.value,
        version=1,
        document_date=date.today(),
        sales_order_id=None,
        source_sales_invoice_id=uuid4(),
        customer_id=uuid4(),
        warehouse_id=uuid4(),
        tax_treatment="STANDARD",
        place_of_supply="UAE",
        shipment_id=None,
    )
    row.id = uuid4()

    service = _actions_service(
        DeliveryNoteService,
        frozenset({SALES_RETURN_CREATE, SALES_INVOICE_CREATE, SHIPMENT_UPDATE}),
    )
    actions = service._available_actions(row, StockDocumentStatus.POSTED, period_locked=False)

    assert "create_return" in actions
    assert "create_sales_invoice" in actions


def test_posted_goods_receipt_exposes_create_bill_when_unbilled() -> None:
    tenant_id = uuid4()
    row = GoodsReceipt(
        tenant_id=tenant_id,
        document_number="GRN-00001",
        status=StockDocumentStatus.POSTED.value,
        version=1,
        document_date=date.today(),
        purchase_order_id=uuid4(),
        supplier_id=uuid4(),
        warehouse_id=uuid4(),
        qc_status="NOT_REQUIRED",
    )
    row.id = uuid4()
    line = GoodsReceiptLine(
        tenant_id=tenant_id,
        goods_receipt_id=row.id,
        line_number=1,
        description="Widget",
        quantity=Decimal("5"),
        qty_billed=Decimal("0"),
        qty_on_hold=Decimal("0"),
        qty_accepted=Decimal("5"),
        qty_rejected=Decimal("0"),
        rate=Decimal("10"),
    )
    line.id = uuid4()
    row.lines = [line]

    service = _actions_service(
        GoodsReceiptService,
        frozenset({PURCHASE_INVOICE_CREATE, GOODS_RECEIPT_DELETE}),
    )
    actions = service._available_actions(row, StockDocumentStatus.POSTED, period_locked=False)

    assert "create_bill" in actions


def test_posted_invoice_documents_expose_note_actions() -> None:
    sales_invoice = SalesInvoice(
        tenant_id=uuid4(),
        document_number="SI-00001",
        status=InvoiceDocumentStatus.POSTED.value,
        version=1,
        invoice_date=date.today(),
        customer_id=uuid4(),
        currency_id=uuid4(),
        base_currency_id=uuid4(),
        exchange_rate=Decimal("1"),
        tax_treatment="STANDARD",
        place_of_supply="UAE",
        grand_total=Decimal("100"),
        base_amount=Decimal("100"),
        balance_due=Decimal("100"),
        amount_paid=Decimal("0"),
        amount_credited=Decimal("0"),
    )
    sales_invoice.id = uuid4()

    purchase_invoice = PurchaseInvoice(
        tenant_id=uuid4(),
        document_number="PI-00001",
        status=InvoiceDocumentStatus.POSTED.value,
        version=1,
        invoice_date=date.today(),
        supplier_id=uuid4(),
        currency_id=uuid4(),
        base_currency_id=uuid4(),
        exchange_rate=Decimal("1"),
        tax_treatment="STANDARD",
        place_of_supply="UAE",
        grand_total=Decimal("100"),
        base_amount=Decimal("100"),
        balance_due=Decimal("100"),
        amount_paid=Decimal("0"),
        amount_debited=Decimal("0"),
    )
    purchase_invoice.id = uuid4()
    purchase_invoice.lines = []

    si_service = _actions_service(SalesInvoiceService, frozenset({CREDIT_NOTE_CREATE}))
    pi_service = _actions_service(PurchaseInvoiceService, frozenset({DEBIT_NOTE_CREATE}))
    sr_service = _actions_service(SalesReturnService, frozenset({CREDIT_NOTE_CREATE}))

    assert "create_credit_note" in si_service._available_actions(
        sales_invoice, InvoiceDocumentStatus.POSTED, period_locked=False
    )
    assert "create_debit_note" in pi_service._available_actions(
        purchase_invoice, InvoiceDocumentStatus.POSTED, period_locked=False
    )
    assert "create_credit_note" in sr_service._available_actions(
        StockDocumentStatus.POSTED, period_locked=False
    )


def test_posted_sales_invoice_exposes_delivery_note_when_qty_remains() -> None:
    tenant_id = uuid4()
    sales_invoice = SalesInvoice(
        tenant_id=tenant_id,
        document_number="SI-00002",
        status=InvoiceDocumentStatus.POSTED.value,
        version=1,
        invoice_date=date.today(),
        customer_id=uuid4(),
        currency_id=uuid4(),
        base_currency_id=uuid4(),
        exchange_rate=Decimal("1"),
        tax_treatment="STANDARD",
        place_of_supply="UAE",
        grand_total=Decimal("100"),
        base_amount=Decimal("100"),
        balance_due=Decimal("100"),
        amount_paid=Decimal("0"),
        amount_credited=Decimal("0"),
    )
    sales_invoice.id = uuid4()
    line = SalesInvoiceLine(
        tenant_id=tenant_id,
        sales_invoice_id=sales_invoice.id,
        line_number=1,
        product_id=uuid4(),
        description="Widget",
        quantity=Decimal("10"),
        qty_delivered=Decimal("3"),
        rate=Decimal("10"),
    )
    line.id = uuid4()
    sales_invoice.lines = [line]

    service = _actions_service(SalesInvoiceService, frozenset({DELIVERY_NOTE_CREATE}))
    actions = service._available_actions(
        sales_invoice, InvoiceDocumentStatus.POSTED, period_locked=False
    )
    assert "create_delivery_note" in actions


def test_posted_purchase_invoice_exposes_goods_receipt_when_qty_remains() -> None:
    tenant_id = uuid4()
    purchase_invoice = PurchaseInvoice(
        tenant_id=tenant_id,
        document_number="PI-00002",
        status=InvoiceDocumentStatus.POSTED.value,
        version=1,
        invoice_date=date.today(),
        supplier_id=uuid4(),
        currency_id=uuid4(),
        base_currency_id=uuid4(),
        exchange_rate=Decimal("1"),
        tax_treatment="STANDARD",
        place_of_supply="UAE",
        grand_total=Decimal("100"),
        base_amount=Decimal("100"),
        balance_due=Decimal("100"),
        amount_paid=Decimal("0"),
        amount_debited=Decimal("0"),
    )
    purchase_invoice.id = uuid4()
    line = PurchaseInvoiceLine(
        tenant_id=tenant_id,
        purchase_invoice_id=purchase_invoice.id,
        line_number=1,
        line_type="PRODUCT",
        product_id=uuid4(),
        description="Widget",
        quantity=Decimal("10"),
        qty_received=Decimal("2"),
        rate=Decimal("10"),
    )
    line.id = uuid4()
    purchase_invoice.lines = [line]

    service = _actions_service(PurchaseInvoiceService, frozenset({GOODS_RECEIPT_CREATE}))
    actions = service._available_actions(
        purchase_invoice, InvoiceDocumentStatus.POSTED, period_locked=False
    )
    assert "create_goods_receipt" in actions


def test_posted_credit_and_debit_notes_expose_refund() -> None:
    credit = CreditNote(
        tenant_id=uuid4(),
        document_number="CN-00001",
        status=InvoiceDocumentStatus.POSTED.value,
        version=1,
        credit_note_date=date.today(),
        customer_id=uuid4(),
        currency_id=uuid4(),
        base_currency_id=uuid4(),
        exchange_rate=Decimal("1"),
        tax_treatment="STANDARD",
        place_of_supply="UAE",
        reason_code="PRICE_ADJUSTMENT",
        grand_total=Decimal("50"),
        base_amount=Decimal("50"),
        amount_applied=Decimal("0"),
        amount_unapplied=Decimal("50"),
    )
    credit.id = uuid4()
    debit = DebitNote(
        tenant_id=uuid4(),
        document_number="DN-00001",
        status=InvoiceDocumentStatus.POSTED.value,
        version=1,
        debit_note_date=date.today(),
        supplier_id=uuid4(),
        currency_id=uuid4(),
        base_currency_id=uuid4(),
        exchange_rate=Decimal("1"),
        tax_treatment="STANDARD",
        place_of_supply="UAE",
        reason_code="PRICE_ADJUSTMENT",
        grand_total=Decimal("50"),
        base_amount=Decimal("50"),
        amount_applied=Decimal("0"),
        amount_unapplied=Decimal("50"),
    )
    debit.id = uuid4()

    cn_service = _actions_service(CreditNoteService, frozenset({CUSTOMER_PAYMENT_CREATE}))
    dn_service = _actions_service(DebitNoteService, frozenset({SUPPLIER_PAYMENT_CREATE}))

    assert "refund" in cn_service._available_actions(
        credit, InvoiceDocumentStatus.POSTED, period_locked=False
    )
    assert "refund" in dn_service._available_actions(
        debit, InvoiceDocumentStatus.POSTED, period_locked=False
    )


def test_fully_delivered_sales_invoice_hides_delivery_note_action() -> None:
    tenant_id = uuid4()
    sales_invoice = SalesInvoice(
        tenant_id=tenant_id,
        document_number="SI-00003",
        status=InvoiceDocumentStatus.POSTED.value,
        version=1,
        invoice_date=date.today(),
        customer_id=uuid4(),
        currency_id=uuid4(),
        base_currency_id=uuid4(),
        exchange_rate=Decimal("1"),
        tax_treatment="STANDARD",
        place_of_supply="UAE",
        grand_total=Decimal("100"),
        base_amount=Decimal("100"),
        balance_due=Decimal("100"),
        amount_paid=Decimal("0"),
        amount_credited=Decimal("0"),
    )
    sales_invoice.id = uuid4()
    line = SalesInvoiceLine(
        tenant_id=tenant_id,
        sales_invoice_id=sales_invoice.id,
        line_number=1,
        product_id=uuid4(),
        description="Widget",
        quantity=Decimal("10"),
        qty_delivered=Decimal("10"),
        rate=Decimal("10"),
    )
    line.id = uuid4()
    sales_invoice.lines = [line]

    service = _actions_service(SalesInvoiceService, frozenset({DELIVERY_NOTE_CREATE}))
    actions = service._available_actions(
        sales_invoice, InvoiceDocumentStatus.POSTED, period_locked=False
    )
    assert "create_delivery_note" not in actions


def test_fully_received_purchase_invoice_hides_goods_receipt_action() -> None:
    tenant_id = uuid4()
    purchase_invoice = PurchaseInvoice(
        tenant_id=tenant_id,
        document_number="PI-00003",
        status=InvoiceDocumentStatus.POSTED.value,
        version=1,
        invoice_date=date.today(),
        supplier_id=uuid4(),
        currency_id=uuid4(),
        base_currency_id=uuid4(),
        exchange_rate=Decimal("1"),
        tax_treatment="STANDARD",
        place_of_supply="UAE",
        grand_total=Decimal("100"),
        base_amount=Decimal("100"),
        balance_due=Decimal("100"),
        amount_paid=Decimal("0"),
        amount_debited=Decimal("0"),
    )
    purchase_invoice.id = uuid4()
    line = PurchaseInvoiceLine(
        tenant_id=tenant_id,
        purchase_invoice_id=purchase_invoice.id,
        line_number=1,
        line_type="PRODUCT",
        product_id=uuid4(),
        description="Widget",
        quantity=Decimal("10"),
        qty_received=Decimal("10"),
        rate=Decimal("10"),
    )
    line.id = uuid4()
    purchase_invoice.lines = [line]

    service = _actions_service(PurchaseInvoiceService, frozenset({GOODS_RECEIPT_CREATE}))
    actions = service._available_actions(
        purchase_invoice, InvoiceDocumentStatus.POSTED, period_locked=False
    )
    assert "create_goods_receipt" not in actions


def test_confirmed_proforma_exposes_advance_and_cost_sheet_actions() -> None:
    service = _actions_service(
        ProformaInvoiceService,
        frozenset({CUSTOMER_PAYMENT_CREATE, COST_SHEET_CREATE}),
    )
    actions = service._available_actions(ProformaInvoiceStatus.CONFIRMED)

    assert "record_advance" in actions
    assert "create_cost_sheet" in actions


def test_draft_proforma_hides_advance_and_cost_sheet_actions() -> None:
    service = _actions_service(
        ProformaInvoiceService,
        frozenset({CUSTOMER_PAYMENT_CREATE, COST_SHEET_CREATE}),
    )
    actions = service._available_actions(ProformaInvoiceStatus.DRAFT)

    assert "record_advance" not in actions
    assert "create_cost_sheet" not in actions


def test_dispatched_shipment_exposes_tracking_and_landed_cost_actions() -> None:
    service = _actions_service(
        ShipmentService,
        frozenset({SHIPMENT_UPDATE, COST_SHEET_CREATE, LANDED_COST_CREATE}),
    )
    actions = service._available_actions(ShipmentStatus.DISPATCHED)

    assert "tracking" in actions
    assert "create_landed_cost" in actions
    assert "create_cost_sheet" in actions


def test_draft_shipment_hides_tracking_and_landed_cost_actions() -> None:
    service = _actions_service(
        ShipmentService,
        frozenset({SHIPMENT_UPDATE, COST_SHEET_CREATE, LANDED_COST_CREATE}),
    )
    actions = service._available_actions(ShipmentStatus.DRAFT)

    assert "tracking" not in actions
    assert "create_landed_cost" not in actions
    assert "create_cost_sheet" in actions

"""Ensure every list repository's search allowlist is valid at construction."""

from unittest.mock import MagicMock

from app.auth.org_repository import OrganizationRepository
from app.auth.repository import AccessRepository
from app.common.attachments.repository import AttachmentRepository
from app.crm.contacts.repository import ContactRepository
from app.crm.customers.repository import CustomerRepository
from app.erp.accounting.accounts.repository import AccountRepository
from app.erp.accounting.customer_payments.repository import CustomerPaymentRepository
from app.erp.accounting.ledger.repository import JournalEntryRepository
from app.erp.accounting.repository import (
    DocumentSequenceRepository,
    PaymentTermRepository,
    TaxRepository,
    TermsTemplateRepository,
)
from app.erp.accounting.supplier_payments.repository import SupplierPaymentRepository
from app.erp.credit_notes.repository import CreditNoteRepository
from app.erp.debit_notes.repository import DebitNoteRepository
from app.erp.exchange_rates.repository import CurrencyRepository
from app.erp.landed_costs.repository import LandedCostRepository
from app.erp.proforma_invoices.repository import ProformaInvoiceRepository
from app.erp.purchase_invoices.repository import PurchaseInvoiceRepository
from app.erp.purchase_orders.repository import PurchaseOrderRepository
from app.erp.quotation.repository import QuotationRepository
from app.erp.sales_invoices.repository import SalesInvoiceRepository
from app.erp.sales_orders.repository import SalesOrderRepository
from app.erp.supplier_products.repository import SupplierProductRepository
from app.inventory_management.categories.repository import CategoryRepository
from app.inventory_management.delivery_notes.repository import DeliveryNoteRepository
from app.inventory_management.goods_receipts.repository import GoodsReceiptRepository
from app.inventory_management.packages.repository import PackageRepository
from app.inventory_management.price_lists.repository import PriceListRepository
from app.inventory_management.products.repository import ProductRepository
from app.inventory_management.purchase_returns.repository import PurchaseReturnRepository
from app.inventory_management.quality_inspections.repository import QualityInspectionRepository
from app.inventory_management.sales_returns.repository import SalesReturnRepository
from app.inventory_management.stock_adjustments.repository import StockAdjustmentRepository
from app.inventory_management.stock_transfers.repository import StockTransferRepository
from app.inventory_management.units.repository import UnitRepository
from app.inventory_management.warehouses.repository import WarehouseRepository
from app.logistics.shipments.repository import ShipmentRepository


def test_list_repositories_construct_with_valid_search_config() -> None:
    session = MagicMock()
    AccessRepository(session)
    OrganizationRepository(session)
    AttachmentRepository(session)
    ContactRepository(session)
    CustomerRepository(session)
    AccountRepository(session)
    CustomerPaymentRepository(session)
    JournalEntryRepository(session)
    DocumentSequenceRepository(session)
    PaymentTermRepository(session)
    TaxRepository(session)
    TermsTemplateRepository(session)
    SupplierPaymentRepository(session)
    CreditNoteRepository(session)
    DebitNoteRepository(session)
    CurrencyRepository(session)
    LandedCostRepository(session)
    ProformaInvoiceRepository(session)
    PurchaseInvoiceRepository(session)
    PurchaseOrderRepository(session)
    QuotationRepository(session)
    SalesInvoiceRepository(session)
    SalesOrderRepository(session)
    SupplierProductRepository(session)
    CategoryRepository(session)
    DeliveryNoteRepository(session)
    GoodsReceiptRepository(session)
    PackageRepository(session)
    PriceListRepository(session)
    ProductRepository(session)
    PurchaseReturnRepository(session)
    QualityInspectionRepository(session)
    SalesReturnRepository(session)
    StockAdjustmentRepository(session)
    StockTransferRepository(session)
    UnitRepository(session)
    WarehouseRepository(session)
    ShipmentRepository(session)

"""Stable logical ERP enums.

These are application-level strings, not PostgreSQL enum declarations.
"""

from enum import StrEnum


class DocumentStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class QuotationStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    CONVERTED = "CONVERTED"


class TaxTreatment(StrEnum):
    REGISTERED = "REGISTERED"
    UNREGISTERED = "UNREGISTERED"
    EXPORT = "EXPORT"
    GCC = "GCC"
    EXEMPT = "EXEMPT"


class TaxCategory(StrEnum):
    STANDARD = "STANDARD"
    ZERO_RATED = "ZERO_RATED"
    EXEMPT = "EXEMPT"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class PlaceOfSupply(StrEnum):
    ABU_DHABI = "ABU_DHABI"
    DUBAI = "DUBAI"
    SHARJAH = "SHARJAH"
    AJMAN = "AJMAN"
    UMM_AL_QUWAIN = "UMM_AL_QUWAIN"
    RAS_AL_KHAIMAH = "RAS_AL_KHAIMAH"
    FUJAIRAH = "FUJAIRAH"
    OUTSIDE_UAE = "OUTSIDE_UAE"


class DiscountType(StrEnum):
    PERCENTAGE = "PERCENTAGE"
    AMOUNT = "AMOUNT"


class PriceListType(StrEnum):
    PERCENT = "PERCENT"
    CUSTOM_RATES = "CUSTOM_RATES"


class DocumentType(StrEnum):
    QUOTATION = "QUOTATION"
    SALES_ORDER = "SALES_ORDER"
    DELIVERY_NOTE = "DELIVERY_NOTE"
    SALES_INVOICE = "SALES_INVOICE"
    CREDIT_NOTE = "CREDIT_NOTE"
    PURCHASE_ORDER = "PURCHASE_ORDER"
    GOODS_RECEIPT = "GOODS_RECEIPT"
    PURCHASE_INVOICE = "PURCHASE_INVOICE"
    DEBIT_NOTE = "DEBIT_NOTE"


class CompanyType(StrEnum):
    CUSTOMER = "CUSTOMER"
    SUPPLIER = "SUPPLIER"
    BOTH = "BOTH"
    OTHER = "OTHER"


class ItemType(StrEnum):
    PRODUCT = "PRODUCT"
    SERVICE = "SERVICE"


class PaymentMethod(StrEnum):
    BANK = "BANK"
    CASH = "CASH"
    UPI = "UPI"
    CREDIT_CARD = "CREDIT_CARD"
    DEBIT_CARD = "DEBIT_CARD"
    CHEQUE = "CHEQUE"
    ONLINE = "ONLINE"
    OTHER = "OTHER"


class StockMovementType(StrEnum):
    PURCHASE = "PURCHASE"
    SALE = "SALE"
    IMPORT = "IMPORT"
    EXPORT = "EXPORT"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    RETURN_IN = "RETURN_IN"
    RETURN_OUT = "RETURN_OUT"
    ADJUSTMENT = "ADJUSTMENT"
    DAMAGE = "DAMAGE"
    OPENING_STOCK = "OPENING_STOCK"


class ShipmentType(StrEnum):
    IMPORT = "IMPORT"
    EXPORT = "EXPORT"
    DOMESTIC = "DOMESTIC"


class NotificationChannel(StrEnum):
    IN_APP = "IN_APP"
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    SMS = "SMS"
    PUSH = "PUSH"


class ChatType(StrEnum):
    DM = "DM"
    GROUP = "GROUP"


class MeetingType(StrEnum):
    INTERNAL = "INTERNAL"
    CUSTOMER = "CUSTOMER"
    SUPPLIER = "SUPPLIER"
    EXTERNAL = "EXTERNAL"


class TenantStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INVITED = "INVITED"
    DISABLED = "DISABLED"


class AuditAction(StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    SUBMIT = "SUBMIT"
    SEND = "SEND"
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"
    CLONE = "CLONE"
    POST = "POST"
    CANCEL = "CANCEL"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"


class AuditStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class BranchStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class EmployeeStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AddressType(StrEnum):
    BRANCH = "BRANCH"
    HEADQUARTERS = "HEADQUARTERS"
    BILLING = "BILLING"
    SHIPPING = "SHIPPING"
    WAREHOUSE = "WAREHOUSE"
    OTHER = "OTHER"


class AttachmentEntityType(StrEnum):
    CUSTOMER = "CUSTOMER"
    CONTACT = "CONTACT"
    PRODUCT = "PRODUCT"
    QUOTATION = "QUOTATION"
    BRANCH = "BRANCH"
    EMPLOYEE = "EMPLOYEE"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"

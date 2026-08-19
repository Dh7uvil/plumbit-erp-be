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
    POST = "POST"
    CANCEL = "CANCEL"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"

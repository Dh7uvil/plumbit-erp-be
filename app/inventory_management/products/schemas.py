"""Product schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.schemas.filters import BaseFilter
from app.common.utils.validators import normalize_required_text
from app.core.enums import ItemType


class ProductFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "sku", "name", "item_type", "selling_rate", "is_active"}
    )
    item_type: ItemType | None = None
    category_id: UUID | None = None
    unit_id: UUID | None = None
    tax_id: UUID | None = None
    is_active: bool | None = None


class ProductCreate(BaseModel):
    item_type: ItemType = ItemType.PRODUCT
    sku: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    sales_description: str | None = None
    unit_id: UUID | None = None
    pieces_per_unit: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=6)
    category_id: UUID | None = None
    selling_rate: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    purchase_rate: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    purchase_description: str | None = None
    tax_id: UUID | None = None
    hs_code: str | None = Field(default=None, max_length=20)
    volume: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    track_inventory: bool = True
    requires_qc: bool | None = None
    income_account_id: UUID | None = None
    purchase_account_id: UUID | None = None
    brand: str | None = Field(default=None, max_length=120)
    origin_country_code: str | None = Field(default=None, max_length=2)
    engine: str | None = Field(default=None, max_length=80)
    alias_2: str | None = Field(default=None, max_length=80)
    alias_3: str | None = Field(default=None, max_length=80)
    alias_4: str | None = Field(default=None, max_length=80)
    rem: str | None = Field(default=None, max_length=200)
    remarks: str | None = None
    max_level: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    default_reorder_level: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=6
    )
    net_weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    gross_weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    price_1: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    price_2: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    stock_input_disabled: bool = False
    secondary_unit_id: UUID | None = None
    secondary_unit_factor: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=6
    )

    @field_validator("sku")
    @classmethod
    def normalize_sku(cls, value: str) -> str:
        return normalize_required_text(value, field_name="sku").upper()

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")

    @field_validator("hs_code")
    @classmethod
    def normalize_hs(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ProductUpdate(BaseModel):
    item_type: ItemType | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sales_description: str | None = None
    unit_id: UUID | None = None
    pieces_per_unit: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=6)
    category_id: UUID | None = None
    selling_rate: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    purchase_rate: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    purchase_description: str | None = None
    tax_id: UUID | None = None
    hs_code: str | None = Field(default=None, max_length=20)
    volume: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    track_inventory: bool | None = None
    requires_qc: bool | None = None
    is_active: bool | None = None
    income_account_id: UUID | None = None
    purchase_account_id: UUID | None = None
    brand: str | None = Field(default=None, max_length=120)
    origin_country_code: str | None = Field(default=None, max_length=2)
    engine: str | None = Field(default=None, max_length=80)
    alias_2: str | None = Field(default=None, max_length=80)
    alias_3: str | None = Field(default=None, max_length=80)
    alias_4: str | None = Field(default=None, max_length=80)
    rem: str | None = Field(default=None, max_length=200)
    remarks: str | None = None
    max_level: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    default_reorder_level: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=6
    )
    net_weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    gross_weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    price_1: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    price_2: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    stock_input_disabled: bool | None = None
    secondary_unit_id: UUID | None = None
    secondary_unit_factor: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=6
    )

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")

    @field_validator("hs_code")
    @classmethod
    def normalize_hs(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ProductPriceBulkItem(BaseModel):
    id: UUID
    selling_rate: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    price_1: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    price_2: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    purchase_rate: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)


class ProductPriceBulkUpdate(BaseModel):
    items: list[ProductPriceBulkItem] = Field(min_length=1)


class ProductRenameSkuRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=80)

    @field_validator("sku")
    @classmethod
    def normalize_sku(cls, value: str) -> str:
        return normalize_required_text(value, field_name="sku").upper()


class ProductWarehouseQty(BaseModel):
    warehouse_id: UUID
    warehouse_name: str
    qty_on_hand: Decimal
    qty_reserved: Decimal
    qty_available: Decimal


class ProductQuantityUnitBreakdown(BaseModel):
    """Winsoft-style PCS / PKT / remainder columns for a quantity row."""

    unit_qty: Decimal
    unit2_qty: Decimal
    remainder_qty: Decimal


class ProductInquiryQuantityRows(BaseModel):
    on_hand: ProductQuantityUnitBreakdown | None = None
    opened: ProductQuantityUnitBreakdown | None = None
    committed: ProductQuantityUnitBreakdown | None = None
    net_available: ProductQuantityUnitBreakdown | None = None


class ProductInquiryResponse(BaseModel):
    product_id: UUID
    packing_label: str | None = None
    qty_on_hand: Decimal
    qty_reserved: Decimal
    qty_available: Decimal
    qty_incoming: Decimal
    qty_opened: Decimal = Decimal("0")
    qty_committed: Decimal = Decimal("0")
    net_available: Decimal = Decimal("0")
    ordered_qty: Decimal = Decimal("0")
    shop_qty: Decimal = Decimal("0")
    warehouse_qty: Decimal = Decimal("0")
    unit2_breakdown: str | None = None
    quantity_rows: ProductInquiryQuantityRows | None = None
    warehouses: list[ProductWarehouseQty]
    avg_cost: Decimal | None = None
    lc_price: Decimal | None = None
    lc_currency_code: str | None = None
    last_sale_date: str | None = None
    last_sale_price: Decimal | None = None
    last_sale_quantity: Decimal | None = None
    last_purchase_date: str | None = None
    last_purchase_price: Decimal | None = None
    last_purchase_quantity: Decimal | None = None
    sku: str | None = None
    name: str | None = None
    alias_2: str | None = None
    alias_3: str | None = None
    alias_4: str | None = None
    volume: Decimal | None = None
    brand: str | None = None
    origin_country_code: str | None = None
    engine: str | None = None
    category_name: str | None = None
    tax_name: str | None = None
    tax_rate: Decimal | None = None
    selling_rate: Decimal | None = None
    price_1: Decimal | None = None
    price_2: Decimal | None = None
    purchase_rate: Decimal | None = None
    net_weight: Decimal | None = None
    gross_weight: Decimal | None = None
    rem: str | None = None
    remarks: str | None = None
    unit_code: str | None = None
    unit2_code: str | None = None


class InventoryListFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"sku", "name", "net_available", "volume", "created_at"}
    )
    sort_by: str = "sku"
    category_id: UUID | None = None
    brand: str | None = None
    engine: str | None = None
    search_type: Literal["default", "starts_with"] = "default"
    tracked_only: bool = True


class ProductInventoryListRow(BaseModel):
    product_id: UUID
    sku: str
    name: str
    net_quantity: Decimal
    net_available: Decimal
    volume: Decimal | None = None
    alias_2: str | None = None
    alias_3: str | None = None
    alias_4: str | None = None
    brand: str | None = None
    engine: str | None = None
    packing_label: str | None = None
    selling_rate: Decimal | None = None
    price_1: Decimal | None = None
    price_2: Decimal | None = None
    purchase_rate: Decimal | None = None
    lc_price: Decimal | None = None
    avg_cost: Decimal | None = None
    last_purchase_price: Decimal | None = None
    ordered_qty: Decimal = Decimal("0")
    shop_qty: Decimal = Decimal("0")
    warehouse_qty: Decimal = Decimal("0")
    qty_on_hand: Decimal = Decimal("0")
    qty_opened: Decimal = Decimal("0")
    qty_committed: Decimal = Decimal("0")


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    item_type: ItemType
    sku: str
    name: str
    sales_description: str | None
    unit_id: UUID | None
    pieces_per_unit: Decimal | None = None
    category_id: UUID | None
    selling_rate: Decimal
    purchase_rate: Decimal
    purchase_description: str | None
    tax_id: UUID | None
    hs_code: str | None
    volume: Decimal | None = None
    track_inventory: bool
    requires_qc: bool
    income_account_id: UUID | None = None
    purchase_account_id: UUID | None = None
    brand: str | None = None
    origin_country_code: str | None = None
    engine: str | None = None
    alias_2: str | None = None
    alias_3: str | None = None
    alias_4: str | None = None
    rem: str | None = None
    remarks: str | None = None
    max_level: Decimal | None = None
    default_reorder_level: Decimal | None = None
    net_weight: Decimal | None = None
    gross_weight: Decimal | None = None
    price_1: Decimal
    price_2: Decimal
    stock_input_disabled: bool
    secondary_unit_id: UUID | None = None
    secondary_unit_factor: Decimal | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None
    qty_on_hand: Decimal | None = None
    qty_opened: Decimal | None = None
    qty_committed: Decimal | None = None
    net_available: Decimal | None = None
    shop_qty: Decimal | None = None
    warehouse_qty: Decimal | None = None
    ordered_qty: Decimal | None = None
    last_sale_date: date | None = None
    last_sale_price: Decimal | None = None
    last_purchase_date: date | None = None
    last_purchase_price: Decimal | None = None

"""Canonical import/export field catalogs. Names match OpenAPI / schema fields."""

from app.common.imex.schemas import ImexField

_LINE = "line"


def _header(*names: tuple[str, str, bool, tuple[str, ...]]) -> list[ImexField]:
    return [
        ImexField(name=name, label=label, required=required, aliases=list(aliases), group="header")
        for name, label, required, aliases in names
    ]


def _lines(*names: tuple[str, str, bool, tuple[str, ...]]) -> list[ImexField]:
    return [
        ImexField(name=name, label=label, required=required, aliases=list(aliases), group=_LINE)
        for name, label, required, aliases in names
    ]


COMMERCIAL_LINES = _lines(
    ("line.sku", "SKU", True, ("item no", "item number", "item_code")),
    ("line.description", "Description", False, ("descriptions", "photo")),
    ("line.quantity", "Quantity", True, ("tt.qty", "total qty", "qty")),
    ("line.unit_price", "Unit price", False, ("price", "price usd", "rate")),
    ("line.carton_qty", "Carton qty", False, ("ctns", "ctn", "carton")),
    ("line.packing_unit", "Packing unit", False, ("pkg", "pckg", "packing")),
    ("line.cbm", "CBM", False, ("tt.cbm", "total cbm")),
    ("line.weight", "Weight", False, ("tt.weight", "total weight")),
    ("line.item_code", "Item code", False, ("item no",)),
)

QUOTATION_FIELDS = (
    _header(
        ("customer_name", "Customer", True, ("customer", "party")),
        ("document_date", "Date", False, ("quote date", "date")),
        ("notes", "Notes", False, ("remark", "incoterm")),
        ("incoterm", "Incoterm", False, ("remark",)),
        ("incoterm_place", "Incoterm place", False, ()),
        ("currency_code", "Currency", False, ("currency",)),
    )
    + COMMERCIAL_LINES
)

PROFORMA_FIELDS = QUOTATION_FIELDS
SALES_INVOICE_FIELDS = (
    _header(
        ("customer_name", "Customer", True, ("customer",)),
        ("document_date", "Invoice date", False, ("date", "invoice date")),
        ("bl_number", "B/L number", False, ("b/l", "bl", "bl_number")),
        ("container_number", "Container", False, ("container",)),
        ("notes", "Notes", False, ("remark",)),
        ("shipping_amount", "Freight", False, ("freight", "loading", "local")),
    )
    + COMMERCIAL_LINES
)
PACKAGE_FIELDS = (
    _header(("sales_order_number", "Sales order", True, ("so", "sales order")))
    + _lines(
        ("line.sku", "SKU", True, ("item no",)),
        ("line.description", "Description", False, ("descriptions",)),
        ("line.quantity", "Quantity", True, ("tt.qty", "qty")),
        ("line.carton_qty", "Carton qty", False, ("ctns",)),
        ("line.packing_unit", "Packing unit", False, ("pkg",)),
        ("line.cbm", "CBM", False, ("tt.cbm",)),
        ("line.weight", "Weight", False, ("tt.weight",)),
        ("line.item_code", "Item code", False, ("item no",)),
    )
)
CUSTOMER_FIELDS = _header(
    ("name", "Name", True, ("customer", "customer name")),
    ("code", "Code", False, ("customer code",)),
    ("trn", "TRN", False, ("tax", "vat")),
    ("email", "Email", False, ()),
    ("phone", "Phone", False, ("tel", "telephone")),
)
SUPPLIER_FIELDS = _header(
    ("name", "Name", True, ("supplier", "supplier name", "vendor")),
    ("code", "Code", False, ("supplier code",)),
    ("trn", "TRN", False, ("tax", "vat")),
    ("email", "Email", False, ()),
    ("phone", "Phone", False, ("tel", "telephone")),
)
PRODUCT_FIELDS = _header(
    ("sku", "SKU", True, ("item no", "item number")),
    ("name", "Name", True, ("description", "descriptions")),
    ("selling_rate", "Selling rate", False, ("price", "unit price")),
    ("purchase_rate", "Purchase rate", False, ()),
)

CATALOGS: dict[str, list[ImexField]] = {
    "quotation": QUOTATION_FIELDS,
    "proforma_invoice": PROFORMA_FIELDS,
    "sales_invoice": SALES_INVOICE_FIELDS,
    "package": PACKAGE_FIELDS,
    "customer": CUSTOMER_FIELDS,
    "supplier": SUPPLIER_FIELDS,
    "product": PRODUCT_FIELDS,
}

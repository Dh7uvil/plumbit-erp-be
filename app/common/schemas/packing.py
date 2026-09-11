"""Optional carton / CBM / weight fields on commercial and packing lines."""

from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class PackingFields(BaseModel):
    carton_qty: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    packing_unit: str | None = Field(default=None, max_length=40)
    cbm: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    item_code: str | None = Field(default=None, max_length=80)

    @field_validator("packing_unit", "item_code")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


def packing_persist(payload: PackingFields | object) -> dict[str, object]:
    """Extract packing columns for ORM create/update dicts."""

    return {
        "carton_qty": getattr(payload, "carton_qty", None),
        "packing_unit": getattr(payload, "packing_unit", None),
        "cbm": getattr(payload, "cbm", None),
        "weight": getattr(payload, "weight", None),
        "item_code": getattr(payload, "item_code", None),
    }

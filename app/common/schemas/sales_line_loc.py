"""Line-level warehouse (Loc) and remarks for sales documents."""

from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class SalesLineLocFields(BaseModel):
    warehouse_id: UUID | None = None
    remarks: str | None = Field(default=None, max_length=2000)

    @field_validator("remarks")
    @classmethod
    def normalize_remarks(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


def sales_line_loc_persist(payload: SalesLineLocFields | object) -> dict[str, object]:
    return {
        "warehouse_id": getattr(payload, "warehouse_id", None),
        "remarks": getattr(payload, "remarks", None),
    }


def fiscal_period_from_date(document_date) -> int:
    return int(document_date.month)

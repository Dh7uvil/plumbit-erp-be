"""Common filtering and allowlisted sorting contracts."""

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

SortOrder = Literal["asc", "desc"]


class BaseFilter(BaseModel):
    """Common collection filters inherited by module-specific schemas."""

    model_config = ConfigDict(extra="forbid")

    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at"})

    search: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    sort_by: str = "created_at"
    sort_order: SortOrder = "desc"

    @field_validator("search")
    @classmethod
    def normalize_search(cls, value: str | None) -> str | None:
        """Trim search input and treat an empty value as absent."""

        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_sort_and_date_range(self) -> "BaseFilter":
        """Reject disallowed sort fields and inverted date ranges."""

        allowed = type(self).allowed_sort_fields
        if self.sort_by not in allowed:
            names = ", ".join(sorted(allowed))
            raise ValueError(f"sort_by must be one of: {names}")
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from > self.date_to
        ):
            raise ValueError("date_from must be before or equal to date_to")
        return self

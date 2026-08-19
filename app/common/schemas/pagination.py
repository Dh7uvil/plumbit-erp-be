"""Bounded pagination schemas and response helpers."""

from math import ceil

from pydantic import BaseModel, Field, field_validator

from app.common.schemas.response import ApiResponse
from app.core.constants import (
    DEFAULT_PAGE_SIZE as DEFAULT_PAGE_SIZE,
)
from app.core.constants import MAX_PAGE_SIZE as MAX_PAGE_SIZE


class PageParams(BaseModel):
    """Validated page parameters with a hard upper bound."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)

    @field_validator("page_size", mode="before")
    @classmethod
    def clamp_page_size(cls, value: object) -> object:
        """Clamp integer page sizes to the configured maximum."""

        if isinstance(value, int) and not isinstance(value, bool):
            return min(value, MAX_PAGE_SIZE)
        if isinstance(value, str):
            try:
                return min(int(value), MAX_PAGE_SIZE)
            except ValueError:
                return value
        return value

    @property
    def offset(self) -> int:
        """Return the SQL offset represented by this page."""

        return (self.page - 1) * self.page_size


class PageMeta(BaseModel):
    """Pagination metadata included in collection responses."""

    page: int
    page_size: int
    total: int
    total_pages: int

    @classmethod
    def from_params(cls, params: PageParams, total: int) -> "PageMeta":
        """Build metadata from validated parameters and a total count."""

        return cls(
            page=params.page,
            page_size=params.page_size,
            total=total,
            total_pages=ceil(total / params.page_size) if total else 0,
        )


def paginated_response[ItemT](
    items: list[ItemT],
    *,
    params: PageParams,
    total: int,
    message: str | None = None,
) -> ApiResponse[list[ItemT]]:
    """Wrap a collection in the standard paginated response envelope."""

    meta = PageMeta.from_params(params, total)
    return ApiResponse(
        data=items,
        message=message,
        meta=meta.model_dump(),
    )

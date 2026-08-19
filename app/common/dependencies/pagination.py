"""FastAPI dependency for bounded pagination."""

from typing import Annotated

from fastapi import Depends, Query

from app.common.schemas.pagination import DEFAULT_PAGE_SIZE, PageParams


async def get_page_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1)] = DEFAULT_PAGE_SIZE,
) -> PageParams:
    """Build validated page parameters, clamping oversized requests."""

    return PageParams(page=page, page_size=page_size)


PaginationDependency = Annotated[PageParams, Depends(get_page_params)]

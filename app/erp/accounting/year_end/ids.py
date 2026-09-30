"""Stable source identifiers for year-end closing journals."""

from uuid import NAMESPACE_OID, UUID, uuid5


def fiscal_year_source_id(fiscal_year: int) -> UUID:
    return uuid5(NAMESPACE_OID, f"year_end_closing:{fiscal_year}")

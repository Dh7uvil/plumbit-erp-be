"""Unit tests for shared list-search helpers."""

from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.search import (
    RelatedSearch,
    ilike_pattern,
    party_search,
    search_clause,
    validate_related_search,
)
from app.crm.contacts.models import Contact
from app.crm.customers.models import Customer


def test_ilike_pattern_escapes_wildcards() -> None:
    assert ilike_pattern("acme") == "%acme%"
    assert ilike_pattern("100%") == r"%100\%%"
    assert ilike_pattern("a_b") == r"%a\_b%"
    assert ilike_pattern(r"a\b") == r"%a\\b%"


def test_search_clause_requires_fields_or_related() -> None:
    with pytest.raises(ValueError, match="search is not supported"):
        search_clause(Contact, tenant_id=uuid4(), search="pat", fields=frozenset(), related=())


def test_related_search_validates_mapped_columns() -> None:
    spec = party_search()
    validate_related_search(spec, Contact)
    with pytest.raises(TypeError, match="no mapped column"):
        validate_related_search(
            RelatedSearch(Customer, local_key="missing", fields=frozenset({"name"})),
            Contact,
        )


def test_search_clause_includes_related_exists() -> None:
    clause = search_clause(
        Contact,
        tenant_id=uuid4(),
        search="Acme",
        fields=frozenset({"name", "email", "phone"}),
        related=(party_search(),),
    )
    assert isinstance(clause, ColumnElement)
    compiled = str(
        clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "ILIKE" in compiled.upper()
    assert "EXISTS" in compiled.upper()
    assert "customers" in compiled

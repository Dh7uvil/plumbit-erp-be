"""Unit tests for note related-entity pairing."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.crm.notes.schemas import NoteCreate, NoteFilter


def test_note_create_requires_body() -> None:
    with pytest.raises(ValidationError):
        NoteCreate(
            body="   ",
            related_entity_type="lead",
            related_entity_id=uuid4(),
        )


def test_note_filter_requires_related_pair() -> None:
    with pytest.raises(ValidationError):
        NoteFilter(related_entity_type="lead")

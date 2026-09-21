"""Unit tests for lead status workflow."""

import pytest

from app.core.enums import LeadStatus
from app.core.exceptions import InvalidStatusTransitionError
from app.crm.leads.workflow import assert_status_transition, assert_editable


def test_qualified_to_contacted_is_allowed() -> None:
    assert_status_transition(LeadStatus.QUALIFIED, LeadStatus.CONTACTED)


def test_converted_lead_is_not_editable() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        assert_editable(LeadStatus.CONVERTED)


def test_new_to_converted_is_rejected() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        assert_status_transition(LeadStatus.NEW, LeadStatus.CONVERTED)

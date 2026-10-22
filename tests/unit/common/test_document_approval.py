from uuid import uuid4

from app.common.document_approval import (
    effective_document_requires_approval,
    hide_unneeded_draft_action,
)


def test_org_disabled_never_requires_approval() -> None:
    creator = uuid4()
    assert (
        effective_document_requires_approval(False, creator, frozenset({creator})) is False
    )


def test_admin_creator_skips_approval_when_org_requires() -> None:
    creator = uuid4()
    assert effective_document_requires_approval(True, creator, frozenset({creator})) is False


def test_non_admin_creator_requires_approval_when_org_requires() -> None:
    creator = uuid4()
    assert effective_document_requires_approval(True, creator, frozenset()) is True


def test_missing_creator_still_requires_approval_when_org_requires() -> None:
    assert effective_document_requires_approval(True, None, frozenset()) is True


def test_draft_hides_direct_action_when_approval_required() -> None:
    assert hide_unneeded_draft_action("send", requires_approval=True, direct_action="send")
    assert (
        hide_unneeded_draft_action("submit", requires_approval=True, direct_action="send") is False
    )
    assert (
        hide_unneeded_draft_action("cancel", requires_approval=True, direct_action="send") is False
    )


def test_draft_hides_submit_when_approval_skipped() -> None:
    assert hide_unneeded_draft_action("submit", requires_approval=False, direct_action="confirm")
    assert (
        hide_unneeded_draft_action("confirm", requires_approval=False, direct_action="confirm")
        is False
    )
    assert (
        hide_unneeded_draft_action("cancel", requires_approval=False, direct_action="issue")
        is False
    )

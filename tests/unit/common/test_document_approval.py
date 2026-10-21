from uuid import uuid4

from app.common.document_approval import effective_document_requires_approval


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

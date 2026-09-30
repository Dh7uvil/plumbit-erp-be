"""Ensure the committed permission catalog snapshot matches the live registry."""

from pathlib import Path

from app.cli.export_permissions_catalog import build_payload, render

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CATALOG_PATH = _REPO_ROOT / "docs" / "permissions-catalog.json"


def test_permissions_catalog_snapshot_matches_live_catalog() -> None:
    assert _CATALOG_PATH.is_file(), (
        "Missing docs/permissions-catalog.json. "
        "Run: uv run export-permissions-catalog"
    )

    expected = render(build_payload())
    actual = _CATALOG_PATH.read_text(encoding="utf-8")
    assert actual == expected, (
        "docs/permissions-catalog.json is out of date. "
        "Run: uv run export-permissions-catalog"
    )

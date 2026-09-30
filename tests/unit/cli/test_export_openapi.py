"""Ensure committed OpenAPI tag snapshots match the live spec."""

from pathlib import Path

from app.cli.export_openapi import build_snapshots, check_snapshots

_REPO_ROOT = Path(__file__).resolve().parents[3]
_OPENAPI_DIR = _REPO_ROOT / "docs" / "openapi"


def test_openapi_snapshots_match_live_spec() -> None:
    assert _OPENAPI_DIR.is_dir(), (
        "Missing docs/openapi/. Run: uv run export-openapi"
    )
    assert check_snapshots(_OPENAPI_DIR), (
        "docs/openapi/ is out of date. Run: uv run export-openapi"
    )


def test_build_snapshots_is_non_empty() -> None:
    snapshots = build_snapshots()
    assert snapshots
    assert all(name.endswith(".json") for name in snapshots)
    assert all(content.endswith("\n") for content in snapshots.values())

"""Export the permission catalog snapshot for frontend codegen."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.auth.catalog import CATALOG_PERMISSIONS, _CATALOG_ACTIONS

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_OUTPUT = _REPO_ROOT / "docs" / "permissions-catalog.json"


def build_payload() -> dict[str, Any]:
    """Build the canonical catalog payload from the live registry."""

    return {
        "permissions": sorted(CATALOG_PERMISSIONS),
        "modules": {
            module: {resource: list(actions) for resource, actions in resources.items()}
            for module, resources in _CATALOG_ACTIONS.items()
        },
    }


def render(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2) + "\n"


def export_catalog(output_path: Path) -> Path:
    payload = build_payload()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render(payload), encoding="utf-8")
    return output_path


def check_catalog(output_path: Path) -> bool:
    if not output_path.is_file():
        print(f"Missing catalog snapshot: {output_path}", file=sys.stderr)
        return False

    expected = render(build_payload())
    actual = output_path.read_text(encoding="utf-8")
    if actual == expected:
        return True

    print(
        "Permission catalog snapshot is out of date.\n"
        f"Run: uv run export-permissions-catalog --output {output_path}",
        file=sys.stderr,
    )
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the permission catalog snapshot.")
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help="Path for the JSON snapshot (default: docs/permissions-catalog.json)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when the committed snapshot does not match the live catalog.",
    )
    args = parser.parse_args()

    if args.check:
        if not check_catalog(args.output):
            raise SystemExit(1)
        return

    path = export_catalog(args.output)
    print(path.relative_to(_REPO_ROOT) if path.is_relative_to(_REPO_ROOT) else path)


if __name__ == "__main__":
    main()

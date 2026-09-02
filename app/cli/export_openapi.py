"""Export per-tag OpenAPI snapshots under docs/openapi/."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from app.main import create_app

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_OUTPUT = _REPO_ROOT / "docs" / "openapi"
_SCHEMA_REF = re.compile(r"^#/components/schemas/(.+)$")


def _slug(tag: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", tag.lower()).strip("-")


def _collect_schema_names(node: object, found: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            match = _SCHEMA_REF.match(ref)
            if match:
                found.add(match.group(1))
        for value in node.values():
            _collect_schema_names(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_schema_names(item, found)


def _referenced_schemas(paths: dict[str, Any], all_schemas: dict[str, Any]) -> dict[str, Any]:
    names: set[str] = set()
    _collect_schema_names(paths, names)
    pending = set(names)
    while pending:
        name = pending.pop()
        schema = all_schemas.get(name)
        if schema is None:
            continue
        nested: set[str] = set()
        _collect_schema_names(schema, nested)
        new_names = nested - names
        names.update(new_names)
        pending.update(new_names)
    return {name: all_schemas[name] for name in sorted(names) if name in all_schemas}


def _tag_description(spec: dict[str, Any], tag_name: str) -> str:
    for tag in spec.get("tags") or []:
        if isinstance(tag, dict) and tag.get("name") == tag_name:
            description = tag.get("description")
            if isinstance(description, str) and description:
                return description
    return tag_name


def export_snapshots(output_dir: Path) -> list[Path]:
    spec = create_app().openapi()
    all_paths: dict[str, Any] = spec.get("paths") or {}
    components: dict[str, Any] = spec.get("components") or {}
    all_schemas: dict[str, Any] = components.get("schemas") or {}
    security_schemes = components.get("securitySchemes") or {}

    tagged: dict[str, dict[str, Any]] = {}
    for path, operations in all_paths.items():
        if not isinstance(operations, dict):
            continue
        for method, operation in operations.items():
            if method.startswith("x-") or not isinstance(operation, dict):
                continue
            tags = operation.get("tags") or ["Untagged"]
            for tag in tags:
                tagged.setdefault(str(tag), {})[path] = operations

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for tag_name, paths in sorted(tagged.items(), key=lambda item: item[0].lower()):
        description = _tag_description(spec, tag_name)
        snapshot = {
            "openapi": spec.get("openapi", "3.1.0"),
            "info": {
                "title": f"Plumbit ERP API — {tag_name}",
                "description": description,
                "version": spec.get("info", {}).get("version", "0.1.0"),
            },
            "tags": [{"name": tag_name, "description": description}],
            "paths": paths,
            "components": {
                "schemas": _referenced_schemas(paths, all_schemas),
                "securitySchemes": security_schemes,
            },
        }
        target = output_dir / f"{_slug(tag_name)}.json"
        target.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        written.append(target)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Write per-tag OpenAPI snapshots.")
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help="Directory for tag JSON files (default: docs/openapi)",
    )
    args = parser.parse_args()
    written = export_snapshots(args.output)
    for path in written:
        print(path.relative_to(_REPO_ROOT) if path.is_relative_to(_REPO_ROOT) else path)


if __name__ == "__main__":
    main()

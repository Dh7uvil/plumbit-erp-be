"""Pure merge and validation for stored table column preferences."""

from __future__ import annotations

from dataclasses import dataclass

from app.common.table_preferences.catalog import LOCKED_COLUMN_ID, TableCatalogEntry
from app.core.exceptions import ValidationError


@dataclass(frozen=True, slots=True)
class NormalizedPreference:
    visible_columns: list[str]
    column_order: list[str]


def _dedupe(keys: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def _as_string_list(value: object, *, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValidationError(
            f"{field_name} must be a list of column keys",
            details={field_name: "must be a list"},
        )
    keys: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValidationError(
                f"{field_name} must contain non-empty strings",
                details={field_name: "invalid item"},
            )
        keys.append(item)
    return keys


def _strip_locked(keys: list[str]) -> list[str]:
    return [key for key in keys if key != LOCKED_COLUMN_ID]


def complete_order(order: list[str], allowed: tuple[str, ...]) -> list[str]:
    """Keep caller order for known keys, then append any missing allowed keys."""

    allowed_set = set(allowed)
    filtered = [key for key in _dedupe(order) if key in allowed_set]
    missing = [key for key in allowed if key not in set(filtered)]
    return filtered + missing


def apply_pinned(
    visible: list[str],
    order: list[str],
    pinned: tuple[str, ...],
) -> tuple[list[str], list[str]]:
    """Force identifier/label columns visible and first. Later keys keep caller order."""

    pinned_set = set(pinned)
    visible_rest = [key for key in visible if key not in pinned_set]
    order_rest = [key for key in order if key not in pinned_set]
    return [*pinned, *visible_rest], [*pinned, *order_rest]


def merge_stored(
    entry: TableCatalogEntry,
    *,
    visible_columns: object,
    column_order: object,
    permissions: frozenset[str],
) -> NormalizedPreference:
    """Lenient merge for GET: drop unknown keys; fall back to defaults if empty."""

    allowed = entry.allowed_keys(permissions)
    allowed_set = set(allowed)
    raw_visible = visible_columns if isinstance(visible_columns, list) else []
    raw_order = column_order if isinstance(column_order, list) else []
    visible = [
        key
        for key in _dedupe([item for item in raw_visible if isinstance(item, str)])
        if key in allowed_set
    ]
    order = complete_order(
        [item for item in raw_order if isinstance(item, str)],
        allowed,
    )
    if not visible:
        return NormalizedPreference(
            visible_columns=entry.default_visible(permissions),
            column_order=entry.default_order(permissions),
        )
    visible, order = apply_pinned(visible, order, entry.pinned_keys(permissions))
    return NormalizedPreference(
        visible_columns=visible,
        column_order=complete_order(order, allowed),
    )


def validate_update(
    entry: TableCatalogEntry,
    *,
    visible_columns: list[str],
    column_order: list[str],
    permissions: frozenset[str],
) -> NormalizedPreference:
    """Strict PUT validation. Unknown keys (except locked `actions`) are rejected."""

    allowed = entry.allowed_keys(permissions)
    allowed_set = set(allowed)
    max_len = max(len(allowed), 1)

    visible = _strip_locked(_as_string_list(visible_columns, field_name="visible_columns"))
    order = _strip_locked(_as_string_list(column_order, field_name="column_order"))

    if len(visible) > max_len or len(order) > max_len:
        raise ValidationError(
            "Too many column keys",
            details={"max_columns": max_len},
        )
    if len(visible) != len(set(visible)):
        raise ValidationError(
            "visible_columns must not contain duplicates",
            details={"field": "visible_columns"},
        )
    if len(order) != len(set(order)):
        raise ValidationError(
            "column_order must not contain duplicates",
            details={"field": "column_order"},
        )

    unknown = sorted({key for key in (*visible, *order) if key not in allowed_set})
    if unknown:
        raise ValidationError(
            "Column keys are not allowed for this table",
            details={"unknown_columns": unknown},
        )

    visible, order = apply_pinned(visible, order, entry.pinned_keys(permissions))
    if not visible:
        raise ValidationError(
            "At least one column must be visible",
            details={"field": "visible_columns"},
        )

    return NormalizedPreference(
        visible_columns=visible,
        column_order=complete_order(order, allowed),
    )

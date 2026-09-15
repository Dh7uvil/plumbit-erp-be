"""Generate unique 3-letter party codes from a name."""

from __future__ import annotations

import re
from collections.abc import Iterable

_SKIP_WORDS = frozenset(
    {
        "LLC",
        "LTD",
        "INC",
        "CORP",
        "CO",
        "LIMITED",
        "FZE",
        "FZCO",
        "PJSC",
        "DMCC",
        "PLC",
        "PTE",
        "THE",
    }
)
_NON_ALNUM = re.compile(r"[^A-Z0-9]+")
_CODE_PATTERN = re.compile(r"^[A-Z0-9]{3}$")
_WALK_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def is_valid_party_code(value: str) -> bool:
    """Return whether ``value`` is exactly three uppercase letters or digits."""

    return _CODE_PATTERN.fullmatch(value) is not None


def candidate_party_code(name: str) -> str:
    """Return the preferred 3-character code for ``name`` before uniqueness."""

    words = _significant_words(name)
    if not words:
        return "XXX"
    if len(words) >= 3:
        return "".join(word[0] for word in words[:3])
    if len(words) == 2:
        first, second = words
        leftover = (
            (second[1:] + first[1:]) if len(second) >= len(first) else (first[1:] + second[1:])
        )
        third = leftover[0] if leftover else "X"
        return f"{first[0]}{second[0]}{third}"
    padded = words[0] + "XXX"
    return padded[:3]


def unique_party_code(name: str, existing: Iterable[str]) -> str:
    """Return a tenant-unique 3-character code derived from ``name``."""

    taken = {code.strip().upper() for code in existing if code and code.strip()}
    candidate = candidate_party_code(name)
    if candidate not in taken:
        return candidate
    code = candidate
    for _ in range(len(_WALK_CHARS) ** 3 - 1):
        code = _increment_code(code)
        if code not in taken:
            return code
    raise RuntimeError("No free 3-character party codes remain")


def _significant_words(name: str) -> list[str]:
    cleaned = _NON_ALNUM.sub(" ", name.upper())
    words = [part for part in cleaned.split() if part]
    significant = [word for word in words if word not in _SKIP_WORDS]
    return significant or words


def _increment_code(code: str) -> str:
    chars = list(code)
    for index in range(2, -1, -1):
        position = _WALK_CHARS.find(chars[index])
        if position < 0:
            position = 0
        if position + 1 < len(_WALK_CHARS):
            chars[index] = _WALK_CHARS[position + 1]
            return "".join(chars)
        chars[index] = _WALK_CHARS[0]
    return "".join(chars)

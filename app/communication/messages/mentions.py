"""Parse @user_id and @everyone mentions from message bodies."""

from __future__ import annotations

import re
from uuid import UUID

_USER_MENTION_PATTERN = re.compile(
    r"@([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)
_EVERYONE_MENTION_PATTERN = re.compile(r"@everyone\b", re.IGNORECASE)


def parse_mentions(body: str) -> tuple[list[UUID], bool]:
    """Return unique mentioned user IDs and whether @everyone was used."""

    mentioned_user_ids = list(dict.fromkeys(UUID(match) for match in _USER_MENTION_PATTERN.findall(body)))
    is_everyone = _EVERYONE_MENTION_PATTERN.search(body) is not None
    return mentioned_user_ids, is_everyone

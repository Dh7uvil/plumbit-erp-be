"""CLI to hard-delete soft-deleted attachments past the retention window."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select

from app.common.attachments.models import Attachment
from app.common.utils.datetime import utcnow
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import async_session_factory, transaction
from app.integrations.storage.client import get_optional_storage

logger = logging.getLogger(__name__)


async def purge_expired(*, retention_years: int, tenant_id: UUID | None = None) -> int:
    """Hard-delete attachment rows and objects whose soft-delete is past retention."""

    cutoff = utcnow() - timedelta(days=365 * retention_years)
    storage = get_optional_storage()
    purged = 0
    async with async_session_factory() as session, transaction(session):
        statement = select(Attachment).where(
            Attachment.deleted_at.is_not(None),
            Attachment.deleted_at <= cutoff,
        )
        if tenant_id is not None:
            statement = statement.where(Attachment.tenant_id == tenant_id)
        result = await session.execute(statement)
        rows = list(result.scalars().all())
        for row in rows:
            if storage is not None:
                try:
                    await storage.delete(key=row.storage_key)
                    if row.thumbnail_storage_key:
                        await storage.delete(key=row.thumbnail_storage_key)
                except Exception:
                    logger.exception(
                        "attachment_purge_storage_failed",
                        extra={"attachment_id": str(row.id), "tenant_id": str(row.tenant_id)},
                    )
                    continue
            await session.delete(row)
            purged += 1
    return purged


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hard-delete soft-deleted attachments past the retention window."
    )
    parser.add_argument(
        "--retention-years",
        type=int,
        default=None,
        help="Override Settings.attachment_retention_years",
    )
    parser.add_argument("--tenant-id", type=UUID, default=None)
    return parser.parse_args()


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    args = _parse_args()
    years = (
        args.retention_years
        if args.retention_years is not None
        else settings.attachment_retention_years
    )
    try:
        purged = asyncio.run(purge_expired(retention_years=years, tenant_id=args.tenant_id))
    except KeyboardInterrupt:
        print("Cancelled", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"Purged {purged} attachment(s)")


if __name__ == "__main__":
    main()

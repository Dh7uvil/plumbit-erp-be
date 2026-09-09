"""CLI poller for the transactional outbox.

Usage: outbox run --batch 20 --interval 2 --worker-id $HOSTNAME
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from app.common.outbox.dispatcher import run_forever
from app.core.logging import configure_logging
from app.wiring import wire_platform


async def _run(*, batch: int, interval: float, worker_id: str) -> None:
    wire_platform()
    await run_forever(batch=batch, interval=interval, worker_id=worker_id)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the transactional outbox dispatcher.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Poll and dispatch pending outbox events")
    run.add_argument("--batch", type=int, default=20, help="Events to claim per cycle")
    run.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Seconds to wait between claim cycles",
    )
    run.add_argument(
        "--worker-id",
        default=os.environ.get("HOSTNAME", "outbox"),
        help="Lock owner recorded on claimed rows",
    )
    return parser.parse_args()


def main() -> None:
    from app.core.config import get_settings

    args = _parse_args()
    configure_logging(get_settings().log_level)
    try:
        asyncio.run(_run(batch=args.batch, interval=args.interval, worker_id=args.worker_id))
    except KeyboardInterrupt:
        print("Stopped", file=sys.stderr)
        raise SystemExit(0) from None


if __name__ == "__main__":
    main()

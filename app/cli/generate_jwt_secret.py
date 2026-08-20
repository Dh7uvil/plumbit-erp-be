"""CLI to generate a cryptographically secure JWT_SECRET value."""

from __future__ import annotations

import argparse
import secrets
import sys

MIN_SECRET_BYTES = 32
DEFAULT_SECRET_BYTES = 48


def generate_secret(num_bytes: int = DEFAULT_SECRET_BYTES) -> str:
    """Return a URL-safe secret backed by `num_bytes` of entropy."""

    if num_bytes < MIN_SECRET_BYTES:
        raise ValueError(f"Secret must use at least {MIN_SECRET_BYTES} bytes of entropy")
    return secrets.token_urlsafe(num_bytes)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a JWT_SECRET value for an .env file.")
    parser.add_argument(
        "--bytes",
        dest="num_bytes",
        type=int,
        default=DEFAULT_SECRET_BYTES,
        help=(
            f"Bytes of entropy to draw (minimum {MIN_SECRET_BYTES}, default {DEFAULT_SECRET_BYTES})"
        ),
    )
    parser.add_argument(
        "--env",
        action="store_true",
        help="Print the secret as a JWT_SECRET=... line ready to paste into .env",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        secret = generate_secret(args.num_bytes)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"JWT_SECRET={secret}" if args.env else secret)


if __name__ == "__main__":
    main()

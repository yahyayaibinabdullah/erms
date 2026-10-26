#!/usr/bin/env python3
"""Explicitly seed the approved generated Arabic UI-translation drafts."""
from __future__ import annotations

import argparse
import json
import os

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed approved generated Arabic UI-translation drafts.",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="Target PostgreSQL URL; defaults to the DATABASE_URL environment variable.",
    )
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="Fill untouched source-copy drafts without correcting any existing translation.",
    )
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url is required when DATABASE_URL is not set")
    return args


def main() -> None:
    args = parse_args()
    # The API database pool is configured at import time, so resolve the
    # explicitly selected target before importing it.
    os.environ["DATABASE_URL"] = args.database_url
    from backend.services.api.database import close_pool, open_pool
    from backend.services.api.localization import (
        synchronize_generated_arabic_drafts,
        synchronize_message_definitions,
    )

    open_pool()
    try:
        synchronize_message_definitions()
        result = synchronize_generated_arabic_drafts(missing_only=args.missing_only)
    finally:
        close_pool()
    print(json.dumps(result, sort_keys=True))
    if result["failed"] or result["awaiting_generation"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

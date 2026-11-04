"""Check every configured source: item count, newest item date, OK/FAIL.

FAIL = fetch error, zero items, or nothing newer than 7 days.
Usage: python scripts/check_feeds.py [--config config.yaml]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from newsletter.config import load_config  # noqa: E402
from newsletter.ingest import fetch_all  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config)
    now = datetime.now(timezone.utc)
    results = fetch_all(cfg, now)

    print(f"{'Source':38} {'Role':8} {'Items':>5} {'AI':>4}  {'Newest (UTC)':16}  Status")
    print("-" * 90)
    fails = 0
    for r in results:
        stale = r.newest is None or r.newest < now - timedelta(days=7)
        ok = r.error is None and r.raw_count > 0 and not stale
        fails += not ok
        newest = r.newest.strftime("%Y-%m-%d %H:%M") if r.newest else "-"
        status = "OK" if ok else "FAIL" + (f" ({r.error})" if r.error else " (stale)" if r.raw_count else " (no items)")
        print(f"{r.name[:38]:38} {r.role:8} {r.raw_count:>5} {r.kept_count:>4}  {newest:16}  {status}")
    print("-" * 90)
    print(f"{len(results) - fails}/{len(results)} OK")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

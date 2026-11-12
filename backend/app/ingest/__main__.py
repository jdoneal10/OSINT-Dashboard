"""Manual ingester entrypoint.

make ingest SOURCE=cbp                      # newest CBP files
make ingest SOURCE=cbp ALL=1                # every robots-allowed CBP series
make ingest SOURCE=cbp FILE=data/raw/cbp/manual/nationwide-drugs-fy20-fy23.csv
make ingest SOURCE=acled SINCE=2018-01-01   # ACLED backfill (incremental without SINCE)
make ingest SOURCE=acled DELETED=1          # ACLED deleted-events reconciliation
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Callable
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.ingest import acled, cbp


def _cbp(args: argparse.Namespace) -> int:
    if args.file:
        return cbp.run_local(Path(args.file), snapshot=args.snapshot_date)
    return cbp.run_remote(all_series=args.all)


def _acled(args: argparse.Namespace) -> int:
    if args.deleted:
        return acled.run_deleted()
    return acled.run_events(since=args.since)


INGESTERS: dict[str, Callable[[argparse.Namespace], int]] = {"cbp": _cbp, "acled": _acled}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ingest")
    parser.add_argument("source", nargs="?", help="source slug: " + ", ".join(INGESTERS))
    parser.add_argument("--since", type=dt.date.fromisoformat, help="YYYY-MM-DD (backfill start)")
    parser.add_argument("--file", help="import a manually downloaded file (cbp)")
    parser.add_argument("--snapshot-date", type=dt.date.fromisoformat, help="override (cbp --file)")
    parser.add_argument("--all", action="store_true", help="every allowed file series (cbp)")
    parser.add_argument("--deleted", action="store_true", help="deleted-events pull (acled)")
    args = parser.parse_args(argv)

    if not args.source:
        parser.error("SOURCE is required (registered: " + ", ".join(INGESTERS) + ")")
    run = INGESTERS.get(args.source)
    if run is None:
        print(f"no ingester registered for {args.source!r}", file=sys.stderr)
        return 2
    configure_logging(get_settings().log_level)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

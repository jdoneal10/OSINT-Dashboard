"""Manual ingester entrypoint: ``make ingest SOURCE=acled SINCE=2026-01-01``."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Callable

# source slug -> run(since). Phase 1 registers acled and cbp here.
INGESTERS: dict[str, Callable[[dt.date | None], int]] = {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ingest")
    parser.add_argument("source", nargs="?", help="source slug, e.g. acled")
    parser.add_argument("--since", type=dt.date.fromisoformat, help="YYYY-MM-DD")
    args = parser.parse_args(argv)

    if not args.source:
        parser.error("SOURCE is required (registered: " + (", ".join(INGESTERS) or "none") + ")")
    run = INGESTERS.get(args.source)
    if run is None:
        print(
            f"no ingester registered for {args.source!r}; ingesters arrive in Phase 1",
            file=sys.stderr,
        )
        return 2
    return run(args.since)


if __name__ == "__main__":
    raise SystemExit(main())

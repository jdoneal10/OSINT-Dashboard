"""Enrichment pipeline orchestration (one pass; the worker schedules it).

    dedupe -> local filter (Ollama) -> collect batches -> extract (Haiku; a backlog goes to the
    Batch API) -> cluster -> Admiralty -> analyze (Sonnet)

Each stage records an ``ingest_runs`` row (job ``pipeline-<stage>``). A stage that cannot run
(Ollama down, budget paused) is logged and the later stages still run on whatever is ready.

    python -m app.enrich.pipeline                    # full pass
    python -m app.enrich.pipeline --stage extract    # one stage
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from typing import Any

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import session_factory
from app.enrich import admiralty, analyze, dedupe, extract, local_filter
from app.enrich.llm.client import BudgetPausedError
from app.ingest.runs import ingest_run

log = logging.getLogger(__name__)


def _dedupe() -> dict[str, Any]:
    with session_factory()() as session, session.begin():
        return {"duplicates": dedupe.mark_duplicates(session)}


def _cluster() -> dict[str, Any]:
    with session_factory()() as session, session.begin():
        counts = dedupe.cluster_events(session)
        counts["scored"] = admiralty.score_clusters(session)
        return counts


STAGES: dict[str, Callable[[], dict[str, Any]]] = {
    "dedupe": _dedupe,
    "filter": local_filter.run_filter,
    "collect": extract.run_collect,
    "extract": extract.run_extract,
    "cluster": _cluster,
    "analyze": analyze.run_analyze,
}


def run_pipeline(stages: list[str] | None = None) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for name in stages or list(STAGES):
        try:
            with ingest_run(f"pipeline-{name}") as run:
                out = STAGES[name]()
                run.params |= {k: v for k, v in out.items() if isinstance(v, int | str)}
                results[name] = out
        except (local_filter.OllamaUnavailableError, BudgetPausedError) as exc:
            log.warning("stage %s skipped: %s", name, exc)
            results[name] = {"skipped": str(exc)}
        except Exception as exc:
            log.exception("stage %s failed", name)
            results[name] = {"error": type(exc).__name__}
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.enrich.pipeline")
    parser.add_argument("--stage", action="append", choices=list(STAGES))
    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)
    results = run_pipeline(args.stage)
    log.info("pipeline: %s", results)
    return 1 if any("error" in r for r in results.values() if isinstance(r, dict)) else 0


if __name__ == "__main__":
    raise SystemExit(main())

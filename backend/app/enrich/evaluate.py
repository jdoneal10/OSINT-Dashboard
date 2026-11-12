"""Extraction precision and relevance-filter recall from the owner's hand labels (Step 6).

    uv run python -m app.enrich.evaluate                       # report for the current prompt
    uv run python -m app.enrich.evaluate --compare-models qwen3:4b,gemma3:4b

Writes ``docs/evaluations/<date>-extraction-<prompt_version>.md``. Labels and notes never leave
the machine; the model comparison calls the local Ollama only.

Definitions
-----------
- **Record precision** (events, seizures): *strict* = correct / labeled; *lenient* counts
  "partly wrong" as correct. The Phase 2 exit criterion (>= 85%) uses strict precision over
  at least 100 labeled documents. Wilson 95% intervals are reported because samples are small.
- **Field errors**: fields named in "partly wrong" labels, including ``person_named``
  (hard rule 3 / ADR 0005).
- **Relevance**: a ``documents``/``relevant`` label says whether the pipeline's decision
  (extracted = relevant, else not) was right; from it each labeled document gets a true
  relevance. **Filter recall** = truly relevant documents the local filter passed
  (score >= threshold) / truly relevant documents.
- **Weighting**: the labeling queue oversamples documents the pipeline rejected, so recall
  and pass rates are weighted by stratum (passed / rejected by the local filter): each
  labeled document stands for (stratum size in the corpus) / (labeled in the stratum).
- Missed records (extraction recall) cannot be measured from record labels; they are out of
  scope for this report.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Document, Label
from app.db.session import session_factory
from app.enrich import extract
from app.enrich.local_filter import LocalFilter, OllamaUnavailableError, document_text

TARGET_PRECISION = 0.85
TARGET_DOCUMENTS = 100
SWEEP = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7)
RECORD_TABLES = ("events", "seizures")


def wilson(successes: float, n: float, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


# --------------------------------------------------------------------------- record precision


@dataclass
class Precision:
    n: int = 0
    correct: int = 0
    partial: int = 0
    incorrect: int = 0

    def add(self, verdict: str) -> None:
        self.n += 1
        if verdict == "correct":
            self.correct += 1
        elif verdict == "partial":
            self.partial += 1
        else:
            self.incorrect += 1

    @property
    def strict(self) -> float | None:
        return self.correct / self.n if self.n else None

    @property
    def lenient(self) -> float | None:
        return (self.correct + self.partial) / self.n if self.n else None


@dataclass
class RecordReport:
    by_table: dict[str, Precision]
    overall: Precision
    field_errors: Counter[str]
    person_named: int
    documents: int  # documents with at least one record label
    wrong_records: list[tuple[str, int]]


def record_precision(session: Session, prompt_version: str) -> RecordReport:
    labels = session.scalars(
        select(Label).where(
            Label.target_table.in_(RECORD_TABLES), Label.prompt_version == prompt_version
        )
    ).all()
    by_table = {t: Precision() for t in RECORD_TABLES}
    overall = Precision()
    fields: Counter[str] = Counter()
    wrong: list[tuple[str, int]] = []
    # One verdict per record: the UI replaces earlier labels; keep the newest if several.
    latest: dict[tuple[str, int], Label] = {}
    for lab in labels:
        key = (lab.target_table, lab.target_id)
        if key not in latest or lab.updated_at > latest[key].updated_at:
            latest[key] = lab
    for (table, target), lab in sorted(latest.items()):
        by_table[table].add(lab.verdict)
        overall.add(lab.verdict)
        if lab.verdict == "partial":
            fields.update(f for f in lab.field.split(",") if f)
        if lab.verdict != "correct":
            wrong.append((table, target))
    return RecordReport(
        by_table=by_table,
        overall=overall,
        field_errors=fields,
        person_named=fields["person_named"],
        documents=len({lab.document_id for lab in latest.values()}),
        wrong_records=wrong,
    )


# --------------------------------------------------------------------------- relevance


@dataclass
class JudgedDocument:
    document_id: int
    truly_relevant: bool
    pipeline_relevant: bool  # extracted
    score: float | None  # local filter score
    weight: float = 1.0


@dataclass
class FilterMetrics:
    model: str
    threshold: float
    recall: float | None
    precision: float | None
    pass_rate: float | None
    sweep: list[tuple[float, float | None, float | None]] = field(default_factory=list)
    seconds_per_doc: float | None = None


def judged_documents(session: Session, threshold: float) -> list[JudgedDocument]:
    """Documents with a relevance label, with stratum weights (passed / rejected filter)."""
    rows = session.execute(
        select(Document.id, Document.pipeline_status, Document.relevance_score, Label.verdict)
        .join(Label, Label.document_id == Document.id)
        .where(
            Label.target_table == "documents",
            Label.target_id == Document.id,
            Label.field == "relevant",
        )
    ).all()
    docs = []
    for doc_id, status, score, verdict in rows:
        pipeline_relevant = status == "extracted"
        truly = pipeline_relevant if verdict == "correct" else not pipeline_relevant
        docs.append(
            JudgedDocument(
                doc_id, truly, pipeline_relevant, float(score) if score is not None else None
            )
        )
    # Corpus stratum sizes among documents the filter has scored.
    scored = select(func.count()).where(
        Document.relevance_score.is_not(None), Document.duplicate_of_id.is_(None)
    )
    passed_total = session.scalar(scored.where(Document.relevance_score >= threshold)) or 0
    rejected_total = session.scalar(scored.where(Document.relevance_score < threshold)) or 0
    passed = [d for d in docs if d.score is not None and d.score >= threshold]
    passed_ids = {d.document_id for d in passed}
    rejected = [d for d in docs if d.document_id not in passed_ids]
    for group, total in ((passed, passed_total), (rejected, rejected_total)):
        for d in group:
            d.weight = total / len(group) if total else 1.0
    return docs


def filter_metrics(
    docs: Iterable[JudgedDocument],
    scores: dict[int, float | None],
    model: str,
    threshold: float,
) -> FilterMetrics:
    docs = list(docs)

    def at(t: float) -> tuple[float | None, float | None, float | None]:
        rel_w = sum(d.weight for d in docs if d.truly_relevant)
        hit_w = sum(
            d.weight for d in docs if d.truly_relevant and (scores.get(d.document_id) or 0) >= t
        )
        pass_w = sum(d.weight for d in docs if (scores.get(d.document_id) or 0) >= t)
        total_w = sum(d.weight for d in docs)
        recall = hit_w / rel_w if rel_w else None
        precision = hit_w / pass_w if pass_w else None
        return recall, precision, (pass_w / total_w if total_w else None)

    recall, precision, pass_rate = at(threshold)
    return FilterMetrics(
        model=model,
        threshold=threshold,
        recall=recall,
        precision=precision,
        pass_rate=pass_rate,
        sweep=[(t, *at(t)[::2]) for t in SWEEP],  # (threshold, recall, pass rate)
    )


def rescore(
    session: Session, docs: list[JudgedDocument], model: str, scorer: LocalFilter | None = None
) -> tuple[dict[int, float | None], float]:
    """Score the labeled documents with another local model (Ollama). Nothing is stored."""
    local = scorer or LocalFilter(model=model)
    out: dict[int, float | None] = {}
    start = time.monotonic()
    for d in docs:
        text = document_text(session.get_one(Document, d.document_id))
        try:
            out[d.document_id] = local.score(text).relevance if text else None
        except (ValidationError, json.JSONDecodeError, httpx.HTTPStatusError):
            out[d.document_id] = None  # invalid model output counts as a miss, as in the pipeline
    per_doc = (time.monotonic() - start) / max(len(docs), 1)
    return out, per_doc


# --------------------------------------------------------------------------- report


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def _ci(p: Precision) -> str:
    lo, hi = wilson(p.correct, p.n)
    return f"{lo:.1%} to {hi:.1%}" if p.n else "n/a"


def verdict(rec: RecordReport) -> str:
    if rec.documents < TARGET_DOCUMENTS:
        return f"**INSUFFICIENT SAMPLE**: {rec.documents} of {TARGET_DOCUMENTS} documents labeled."
    strict = rec.overall.strict or 0.0
    status = "PASS" if strict >= TARGET_PRECISION else "FAIL"
    return f"**{status}**: strict precision {_pct(strict)} (target {TARGET_PRECISION:.0%})."


def render(
    prompt_version: str,
    rec: RecordReport,
    docs: list[JudgedDocument],
    filters: list[FilterMetrics],
    today: dt.date,
) -> str:
    lines = [
        f"# Extraction evaluation: {prompt_version}",
        "",
        f"- **Date:** {today.isoformat()}",
        f"- **Prompt version judged:** `{prompt_version}`",
        f"- **Documents with record labels:** {rec.documents}; "
        f"**with relevance labels:** {len(docs)}",
        f"- **Exit criterion (Phase 2):** {verdict(rec)}",
        "",
        "Generated by `python -m app.enrich.evaluate` from the owner's hand labels. "
        "Labels, notes and article text stay local; this report holds counts and record ids "
        "only.",
        "",
        "## Record precision",
        "",
        "| Records | Labeled | Correct | Partly wrong | Wrong | Strict | 95% CI | Lenient |",
        "|---|---:|---:|---:|---:|---:|---|---:|",
    ]
    for name, p in [*rec.by_table.items(), ("**all**", rec.overall)]:
        lines.append(
            f"| {name} | {p.n} | {p.correct} | {p.partial} | {p.incorrect} | "
            f"{_pct(p.strict)} | {_ci(p)} | {_pct(p.lenient)} |"
        )
    lines += ["", "## Field errors (partly wrong records)", ""]
    if rec.field_errors:
        lines += ["| Field | Records |", "|---|---:|"]
        lines += [f"| {f} | {n} |" for f, n in rec.field_errors.most_common()]
    else:
        lines.append("None recorded.")
    lines += [
        "",
        f"**Hard rule 3 (ADR 0005):** {rec.person_named} record(s) named a person other than "
        "a reported criminal-group leader.",
        "",
        "## Relevance filter",
        "",
        "Recall and pass rate are weighted by filter stratum (see module docstring).",
        "",
    ]
    if not docs:
        lines.append("No relevance labels yet.")
    else:
        truly = sum(d.truly_relevant for d in docs)
        lines += [
            f"Labeled documents: {len(docs)} ({truly} truly relevant).",
            "",
            "| Model | Threshold | Recall | Precision | Pass rate | s/doc |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for m in filters:
            spd = f"{m.seconds_per_doc:.1f}" if m.seconds_per_doc is not None else "—"
            lines.append(
                f"| {m.model} | {m.threshold:.2f} | {_pct(m.recall)} | {_pct(m.precision)} | "
                f"{_pct(m.pass_rate)} | {spd} |"
            )
        lines += ["", "### Threshold sweep (recall / pass rate)", ""]
        header = "| Threshold | " + " | ".join(m.model for m in filters) + " |"
        lines += [header, "|---|" + "---:|" * len(filters)]
        for i, t in enumerate(SWEEP):
            cells = [f"{_pct(m.sweep[i][1])} / {_pct(m.sweep[i][2])}" for m in filters]
            lines.append(f"| {t:.1f} | " + " | ".join(cells) + " |")
    if rec.wrong_records:
        lines += [
            "",
            "## Records to review",
            "",
            ", ".join(f"{t}:{i}" for t, i in rec.wrong_records),
        ]
    lines += [
        "",
        "## Caveats",
        "",
        "- Precision only: records the model missed are not measured here.",
        "- Small samples: read the confidence interval, not just the point estimate.",
        "- Relevance truth comes from one analyst's judgment of the intelligence requirements.",
        "",
    ]
    return "\n".join(lines)


def run(
    prompt_version: str | None = None,
    compare_models: list[str] | None = None,
    out_dir: Path | None = None,
    today: dt.date | None = None,
    scorer_factory: Callable[[str], LocalFilter] | None = None,
) -> Path:
    settings = get_settings()
    version = prompt_version or extract.PROMPT_VERSION
    threshold = settings.relevance_threshold
    with session_factory()() as session:
        rec = record_precision(session, version)
        docs = judged_documents(session, threshold)
        stored = {d.document_id: d.score for d in docs}
        filters = [filter_metrics(docs, stored, f"{settings.relevance_model} (stored)", threshold)]
        for model in compare_models or []:
            scorer = scorer_factory(model) if scorer_factory else None
            scores, per_doc = rescore(session, docs, model, scorer)
            m = filter_metrics(docs, scores, model, threshold)
            m.seconds_per_doc = per_doc
            filters.append(m)
    today = today or dt.datetime.now().astimezone().date()  # the owner's local date
    out_dir = out_dir or settings.repo_root / "docs" / "evaluations"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{today.isoformat()}-extraction-{version}.md"
    path.write_text(render(version, rec, docs, filters, today), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.enrich.evaluate")
    parser.add_argument("--prompt-version", help=f"default: {extract.PROMPT_VERSION}")
    parser.add_argument(
        "--compare-models",
        help="comma-separated Ollama models to re-score the labeled documents with",
    )
    args = parser.parse_args(argv)
    models = [m.strip() for m in (args.compare_models or "").split(",") if m.strip()]
    try:
        path = run(args.prompt_version, models)
    except OllamaUnavailableError as exc:
        print(f"Model comparison needs Ollama: {exc}")
        return 2
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

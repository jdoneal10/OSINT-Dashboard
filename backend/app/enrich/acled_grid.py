"""ACLED grid pass (ADR 0014): classify ACLED notes for criminal interaction with the grid.

ACLED events are structured and never go through article extraction, so the reporting behind
IR 9 that ACLED holds (groups cutting power, attacks on utility crews, extortion, fuel theft)
was never recorded. This pass sends the notes of ACLED events that mention the electrical
grid or fuel theft to Haiku, one event per request, and stores the verdict on the event:

- ``grid_interaction``: one kind from the owner framework (§2), or none;
- ``energy_indicators``: reported facts that suggest theft without claiming it;
- for a theft case, the ``energy_*`` detail, exactly as for news extraction.

Rules (owner framework §2, CLAUDE.md):

- **As reported.** Every kind needs the note to tie the act to criminal or armed actors; the
  model quotes the note, and a verdict whose quote is not in the note is quarantined.
- **No inference of sites, no people.** Output is categories and a quote only; victims such as
  utility workers stay roles. The municipal inference is a later, labeled analytic layer.
- **Provenance.** ``grid_classifications`` keeps model, prompt version, tokens and the hash
  of the classified notes; an ACLED edit to the notes queues the event again.
- **Licence.** ACLED's written consent covers sending its data to Claude (ADR 0006); the
  gateway's guard still checks every request.

A backlog of ``llm_batch_threshold`` or more goes through the Batch API (50%); smaller runs
are real-time. Run as pipeline stage ``grid`` or by hand:

    python -m app.enrich.acled_grid                # one pass (collect, then submit or call)
    python -m app.enrich.acled_grid --sample 20    # real-time on 20 candidates, show verdicts
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import Event, GridClassification, Source
from app.db.session import session_factory
from app.enrich.acled_notes import build_user, current_notes_hash, notes_hash, quote_found
from app.enrich.extract import EnergyIndicator, EnergyTheftDetail, GridKind
from app.enrich.llm import batch as llm_batch
from app.enrich.llm.client import BudgetPausedError, Gateway, Provenance
from app.enrich.llm.pricing import HAIKU

log = logging.getLogger(__name__)

STAGE = "grid"
PROMPT_VERSION = "grid-v3"  # v2: outages need an area; v3: fuel thieves as actors count
MAX_TOKENS = 1000
EFFORT = "low"
SOURCE = "acled"

# Notes worth classifying: the electrical grid, utility crews, cable theft, or fuel theft
# (the owner's fuel_theft indicator). Postgres regex, case-insensitive. Broad on purpose:
# the model, not this pattern, decides; most matches are service protests and get no kind.
CANDIDATE_PATTERN = (
    r"(electric|power (outage|cut|line|plant|station|supply|grid|pole|tower|substation)"
    r"|blackout|substation|transformer|high[- ]voltage|\mCFE\M"
    r"|Federal Electricity Commission|utility (pole|worker|crew|company)|without power"
    r"|(copper|cable|wire) theft|(stole|steal|stealing|stolen) (copper|cable|wire)"
    r"|huachicol|fuel theft|(stole|steal|stealing|stolen) fuel|pipeline|PEMEX"
    r"|clandestine tap|illegal tap|fuel tapp)"
)


EVIDENCE_MAX = 200


def trim_quote(value: object, limit: int) -> object:
    """A quote longer than ``limit``, cut at the last word boundary that fits, with "…".

    The model sometimes quotes a little past the limit and trails off into junk (seen
    2026-11-23: a 207-character quote followed by "although"). The limit stays in the schema
    sent to the model; this keeps a long quote instead of quarantining the whole verdict.
    """
    if not isinstance(value, str) or len(value) <= limit:
        return value
    cut = value[: limit - 1]
    if " " in cut:
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip(" ,;:") + "…"


class GridVerdict(BaseModel):
    kind: GridKind | None = Field(
        description="The one kind the note reports, or null if none applies"
    )
    indicators: list[EnergyIndicator] = Field(
        description="Indicators the note reports; empty if none", max_length=5
    )
    theft: EnergyTheftDetail | None = Field(
        description="Required when kind is theft; null otherwise"
    )
    evidence: str | None = Field(
        description="Verbatim quote from the note (<= 200 chars) supporting the kind and "
        "indicators; null when both are empty",
        max_length=200,
    )

    @field_validator("evidence", mode="before")
    @classmethod
    def _trim_evidence(cls, value: object) -> object:
        return trim_quote(value, EVIDENCE_MAX)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.kind == "theft") != (self.theft is not None):
            raise ValueError("theft detail is required exactly when kind is 'theft'")
        if (self.kind or self.indicators) and not self.evidence:
            raise ValueError("a kind or indicator needs an evidence quote")
        return self


SYSTEM = """\
You read one ACLED event note about Mexico and record whether it reports criminal interaction \
with the electrical grid, and any energy indicators. This feeds an UNCLASSIFIED open-source \
analytic aid. Record only what the note reports; never infer.

CRIMINAL LINK. A kind applies only when the note ties the act to criminal or armed actors: a \
named criminal group or cartel, organized crime, armed men, gunmen, hitmen, an unidentified \
armed group, or extortion. Not kinds: residents protesting over power service, prices or \
outages; ordinary outages, accidents and weather; acts by police, military or officials \
doing their jobs; theft by unidentified thieves with no criminal-group link.

KIND (at most one; null if none applies). If several apply, take the first in this order:
1. theft: electricity stolen by or for criminal activity (illegal hookups, meter bypass, a \
site or network drawing power illegally). Then fill theft:
   - method: meter_bypass, illegal_line_connection, transformer_or_feeder_tampering, \
insider_facilitation, unknown.
   - powered, as reported: crypto_mining, cultivation, drug_lab, warehouse_or_storage, \
refrigeration, communications, residential_compound, other.
   - facilitator, by role only: utility_employee, contractor, electrician, official, \
property_manager, none_reported.
   - scale: the kW, MW or equipment count the note gives, else null. Never estimate.
2. attack_on_utility_workers: criminal or armed actors attack, kill, kidnap, threaten or \
rob crews of the CFE (Federal Electricity Commission) or its contractors.
3. deliberate_outage_or_sabotage: criminal or armed actors cut power or damage substations, \
towers, lines or transformers on purpose, including during roadblocks or clashes.
4. extortion_or_service_control: a criminal group charges for, rations, controls or cuts \
service to a community, or extorts the utility or its contractors.
5. infrastructure_theft: theft of transformers, cable or copper that the note ties to a \
criminal group.
6. utility_withdrawal: the CFE or contractors suspend work or service in an area because of \
insecurity or criminal threats.

INDICATORS (zero or more; they never make a theft case on their own):
- mining_equipment_seized: cryptocurrency-mining equipment found in a raid or seizure.
- high_load_site: a grow, lab or compound reported with heavy electrical equipment (lights, \
air conditioning, generators, refrigeration).
- outage_in_contested_area: an outage across an area (a town, neighborhood or region) that \
the note places where a criminal group operates or fights (named or described). Power cut to \
one house or building does not count, and a protest over outages alone does not count.
- utility_insider_reported: a CFE or utility employee reported as linked to a criminal group.
- fuel_theft: fuel theft by a criminal group (pipeline taps, huachicol, stolen fuel), or fuel \
thieves (huachicoleros) named as the actors or the people targeted. Not fuel smuggling and not \
protests about fuel. Fuel theft is never the theft kind.

EVIDENCE. When kind or indicators are set, quote the words of the note that show it, \
verbatim, at most 200 characters. Otherwise null.

Never name a person. Never describe the positions, units or response of security forces.\
"""


def candidates() -> Select[int]:
    """ACLED events whose notes match and have no current verdict (none, or stale)."""
    g = GridClassification
    return (
        select(Event.id)
        .join(Source, Source.id == Event.source_id)
        .outerjoin(g, g.event_id == Event.id)
        .where(
            Source.slug == SOURCE,
            Event.description.is_not(None),
            Event.description.op("~*")(CANDIDATE_PATTERN),
            or_(
                g.event_id.is_(None),
                (g.status != "batched")
                & ((g.notes_sha256 != current_notes_hash()) | (g.prompt_version != PROMPT_VERSION)),
            ),
        )
        .order_by(Event.event_date.desc(), Event.id)
    )


def _clear(ev: Event) -> None:
    ev.grid_interaction = None
    ev.energy_indicators = []
    ev.energy_method = ev.energy_facilitator = ev.energy_scale = None
    ev.energy_powered = []


def clear_stale(session: Session) -> int:
    """Drop verdicts whose notes ACLED edited so they no longer match the pattern."""
    g = GridClassification
    stale = list(
        session.scalars(
            select(g.event_id)
            .join(Event, Event.id == g.event_id)
            .where(
                g.status != "batched",
                g.notes_sha256 != current_notes_hash(),
                or_(
                    Event.description.is_(None),
                    Event.description.op("!~*")(CANDIDATE_PATTERN),
                ),
            )
        )
    )
    for event_id in stale:
        _clear(session.get_one(Event, event_id))
    if stale:
        session.execute(delete(g).where(g.event_id.in_(stale)))
    return len(stale)


def _row(session: Session, event_id: int) -> GridClassification:
    row = session.get(GridClassification, event_id)
    if row is None:
        row = GridClassification(event_id=event_id, notes_sha256="", status="batched")
        session.add(row)
    return row


def store(
    event_id: int, verdict: GridVerdict, tokens: tuple[int, int], sent_hash: str | None = None
) -> str:
    """Apply a validated verdict. Returns 'done', 'quarantined' or 'stale'."""
    with session_factory()() as session, session.begin():
        ev = session.get(Event, event_id)
        if ev is None:
            return "stale"
        notes = ev.description or ""
        row = _row(session, event_id)
        sent = sent_hash or (row.notes_sha256 if row.status == "batched" else None)
        if sent and sent != notes_hash(notes):  # ACLED edited the notes meanwhile: redo
            if row in session.new:
                session.expunge(row)
            else:
                session.delete(row)
            return "stale"
        row.notes_sha256 = notes_hash(notes)
        row.llm_model, row.prompt_version = HAIKU, PROMPT_VERSION
        row.llm_input_tokens, row.llm_output_tokens = tokens
        row.classified_at = dt.datetime.now(dt.UTC)
        _clear(ev)
        quote = verdict.evidence
        if quote and not quote_found(quote, ev):
            row.status, row.evidence = "quarantined", quote[:400]
            log.warning("grid verdict for event %d quoted text not in its notes", event_id)
            return "quarantined"
        row.status, row.evidence = "done", quote
        ev.grid_interaction = verdict.kind
        ev.energy_indicators = list(dict.fromkeys(verdict.indicators))
        if verdict.theft is not None:
            ev.energy_method = verdict.theft.method
            ev.energy_powered = list(dict.fromkeys(verdict.theft.powered))
            ev.energy_facilitator = verdict.theft.facilitator
            ev.energy_scale = verdict.theft.scale
        return "done"


def _set_quarantined(event_id: int) -> None:
    with session_factory()() as session, session.begin():
        ev = session.get(Event, event_id)
        if ev is None:
            return
        row = _row(session, event_id)
        row.status, row.prompt_version = "quarantined", PROMPT_VERSION
        row.notes_sha256 = notes_hash(ev.description or "")
        _clear(ev)


def _requeue(event_id: int) -> None:
    with session_factory()() as session, session.begin():
        session.execute(delete(GridClassification).where(GridClassification.event_id == event_id))


def _item(session: Session, event_id: int) -> llm_batch.BatchItem:
    ev = session.get_one(Event, event_id)
    return llm_batch.BatchItem(
        custom_id=f"event-{event_id}",
        document_id=event_id,  # the batch's item key; here an event id
        user=build_user(ev),
        provenance=Provenance(event_ids=(event_id,)),
    )


def batch_job() -> llm_batch.BatchJob[GridVerdict]:
    def rebuild(event_id: int) -> llm_batch.BatchItem:
        with session_factory()() as session:
            return _item(session, event_id)

    def store_result(event_id: int, verdict: GridVerdict, tokens: tuple[int, int]) -> None:
        store(event_id, verdict, tokens)

    return llm_batch.BatchJob(
        stage=STAGE,
        model=HAIKU,
        prompt_version=PROMPT_VERSION,
        system=SYSTEM,
        output_model=GridVerdict,
        max_tokens=MAX_TOKENS,
        effort=EFFORT,
        rebuild=rebuild,
        store=store_result,
        fail=_set_quarantined,
        requeue=_requeue,
    )


def submit_batch(gateway: Gateway, ids: list[int]) -> int:
    with session_factory()() as session:
        items = [_item(session, i) for i in ids]
    row = llm_batch.submit(gateway, batch_job(), items)
    if row is None:
        return 0
    with session_factory()() as session, session.begin():
        for event_id in row.items.values():
            ev = session.get_one(Event, int(event_id))
            cls = _row(session, int(event_id))
            cls.status, cls.prompt_version = "batched", PROMPT_VERSION
            cls.notes_sha256 = notes_hash(ev.description or "")
    return row.n_requests


def call_one(gateway: Gateway, event_id: int) -> str:
    """Real-time classification of one event. Returns the stored status."""
    with session_factory()() as session:
        item = _item(session, event_id)
        sent = notes_hash(session.get_one(Event, event_id).description or "")
    result = gateway.call(
        stage=STAGE, model=HAIKU, prompt_version=PROMPT_VERSION, system=SYSTEM,
        user=item.user, output_model=GridVerdict, provenance=item.provenance,
        max_tokens=MAX_TOKENS, effort=EFFORT,
    )  # fmt: skip
    if not result.ok or result.parsed is None:
        _set_quarantined(event_id)
        return "quarantined"
    return store(event_id, result.parsed, (result.input_tokens, result.output_tokens), sent)


def run_grid(limit: int = 50, gateway: Gateway | None = None) -> dict[str, int]:
    """Pipeline stage ``grid``: collect finished batches, then classify what is queued."""
    gateway = gateway or Gateway()
    settings = get_settings()
    counts = llm_batch.collect(gateway, {STAGE: batch_job()})
    out: dict[str, int] = {f"collected_{k}": v for k, v in counts.items() if v}
    with session_factory()() as session, session.begin():
        out["stale_cleared"] = clear_stale(session)
    with session_factory()() as session:
        query = candidates()
        backlog = session.scalar(select(func.count()).select_from(query.subquery())) or 0
        cap = settings.llm_batch_max_requests if backlog >= settings.llm_batch_threshold else limit
        ids = list(session.scalars(query.limit(cap)))
    out["backlog"] = backlog
    if backlog >= settings.llm_batch_threshold:
        try:
            out["batched"] = submit_batch(gateway, ids)
        except BudgetPausedError:
            log.warning("budget paused; grid batch not submitted")
            out["batched"] = 0
        return out
    for event_id in ids:
        try:
            status = call_one(gateway, event_id)
        except BudgetPausedError:
            log.warning("budget paused; stopping the grid pass")
            break
        out[status] = out.get(status, 0) + 1
    log.info("grid pass: %s", out)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.enrich.acled_grid")
    parser.add_argument("--sample", type=int, help="classify N candidates now and show them")
    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)
    if not args.sample:
        log.info("grid pass: %s", run_grid())
        return 0
    gateway = Gateway()
    with session_factory()() as session:
        ids = list(session.scalars(candidates().limit(args.sample)))
    for event_id in ids:
        status = call_one(gateway, event_id)
        with session_factory()() as session:
            ev = session.get_one(Event, event_id)
            row = session.get(GridClassification, event_id)
            print(
                f"{ev.source_key} {status}: kind={ev.grid_interaction} "
                f"indicators={ev.energy_indicators} method={ev.energy_method} "
                f"evidence={row.evidence if row else None!r}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

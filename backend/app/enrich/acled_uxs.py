"""ACLED UxS pass (ADR 0009 amendment 1): classify ACLED notes for criminal unmanned systems.

ACLED events are structured and never go through article extraction, so the drone reporting
behind IR 8 that ACLED holds (explosive drone attacks, drones seized or shot down, drone
surveillance by criminal groups) was never recorded in the UxS fields. This pass sends the
notes of ACLED events that mention drones or other unmanned systems to Haiku, one event per
request, and stores the verdict on the event in the same fields news extraction fills:
``uxs_activity``, ``uxs_platform``, ``uxs_missions`` and ``uxs_payloads``.

Rules (owner framework §1, CLAUDE.md):

- **As reported, criminal only.** The note must tie the unmanned system to criminal or armed
  actors. Drones of police, military, the National Guard or foreign governments are never
  recorded (hard rule 4: track threats, not friendly forces); a criminal drone attack on
  security forces is recorded as a mission and the place at the note's precision, never the
  units, positions or response.
- **Quoted.** The model quotes the note; a verdict whose quote is not in the note is
  quarantined.
- **Provenance.** ``uxs_classifications`` keeps model, prompt version, tokens and the hash
  of the classified notes; an ACLED edit to the notes queues the event again.
- **Licence.** ACLED's written consent covers sending its data to Claude (ADR 0006); the
  gateway's guard still checks every request.

A backlog of ``llm_batch_threshold`` or more goes through the Batch API (50%); smaller runs
are real-time. Run as pipeline stage ``uxs`` or by hand:

    python -m app.enrich.acled_uxs                # one pass (collect, then submit or call)
    python -m app.enrich.acled_uxs --sample 20    # real-time on 20 candidates, show verdicts
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
from typing import Self

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import Event, Source, UxsClassification
from app.db.session import session_factory
from app.enrich.acled_notes import build_user, current_notes_hash, notes_hash, quote_found
from app.enrich.extract import UxsDetail
from app.enrich.llm import batch as llm_batch
from app.enrich.llm.client import BudgetPausedError, Gateway, Provenance
from app.enrich.llm.pricing import HAIKU

log = logging.getLogger(__name__)

STAGE = "uxs"
PROMPT_VERSION = "uxs-v4"  # v2: separate events; v3: ACLED actors; v4: crews, drone payloads
MAX_TOKENS = 1000
EFFORT = "low"
SOURCE = "acled"

# Notes worth classifying: drones and other unmanned systems. Postgres regex,
# case-insensitive. Broad on purpose: the model, not this pattern, decides; police and
# military drones match too and get no verdict. Not "UAS": it matches the Autonomous
# University of Sinaloa.
CANDIDATE_PATTERN = (
    r"(\mdrones?\M|\mUAVs?\M|unmanned|quadcopter|\mFPV\M|semi-?submersible"
    r"|narco-?sub)"
)


class UxsVerdict(BaseModel):
    uxs: UxsDetail | None = Field(
        description="The criminal unmanned-system detail the note reports, or null if none"
    )
    evidence: str | None = Field(
        description="Verbatim quote from the note (<= 200 chars) showing the unmanned system "
        "and its use; null when uxs is null",
        max_length=200,
    )

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.uxs is not None and not self.evidence:
            raise ValueError("a UxS verdict needs an evidence quote")
        return self


SYSTEM = """\
You read one ACLED event note about Mexico and record whether it reports a drone or other \
unmanned system used, seized, bought, built, modified, taught or prosecuted in connection \
with criminal or armed groups. This feeds an UNCLASSIFIED open-source analytic aid. Record \
only what the note reports; never infer.

CRIMINAL LINK. Set uxs only when the note ties the unmanned system to criminal or armed \
actors: a named criminal group or cartel, organized crime, armed men, gunmen, hitmen, an \
unidentified armed group, or a self-defense or armed civilian group. The Actors line \
counts: drones seized or found in an event whose actors include a criminal or armed group \
(for example "Unidentified Gang" or "Unidentified Armed Group") are tied to that group. \
Set uxs to null for:
- drones of police, the military, the National Guard, prosecutors or any government, \
Mexican or foreign, including drones they use to search, patrol or locate people;
- drones of journalists, residents, companies or event organizers, and drones merely seen \
with no actor tied to them;
- notes that mention drones only as background (for example a law, a speech or a program);
- semi-submersibles or boats with people aboard or arrested on them: they are crewed, not \
unmanned;
- drone use the note says is a separate event ("coded separately", "an earlier attack") or \
gives only as the cause or context of this event (people fleeing, a protest, a clash \
before or after a drone attack): that event carries it, not this one.

UXS (null if the rule above is not met):
- activity: employment (a criminal or armed group used it: an attack, a flight, \
surveillance, dropping explosives); recovery_or_seizure (drones or drone parts of a \
criminal group seized, found, recovered, shot down, jammed or disabled, including \
explosives or IEDs the note says were made to be launched from drones, even with no drone \
found); \
procurement_or_import; assembly_or_modification (a workshop, adapted drones); training; \
prosecution (charges or sentences for drone use).
- platform: suas_multirotor (commercial quadcopters such as DJI or Autel), fpv \
(first-person-view racing-style drones), fixed_wing, heavy_lift_or_hybrid, ugv (ground \
robot), usv (unmanned boat, or a semi-submersible the note says had no crew); unknown when \
the note does not say. A note that just says "drones" is unknown.
- missions, as the note reports them (zero or more): surveillance, route_security, \
overwatch, attack, logistics (carrying drugs or supplies), coercion_or_propaganda, \
surveillance_of_security_forces, monitoring_economic_activity.
- payloads (zero or more): explosive_or_grenade, ied, camera_or_thermal, \
release_mechanism, supply, loudspeaker_or_light; none_reported when the note names none.

SECURITY FORCES. When criminal drones attack or watch police, soldiers or the National \
Guard, record the mission (attack or surveillance_of_security_forces) and nothing more: \
never describe their units, positions, movements or response.

EVIDENCE. When uxs is set, quote the words of the note that show the unmanned system and \
its use, verbatim, at most 200 characters; leave out unit names and positions of security \
forces, joining fragments with "..." if needed. Otherwise null.

Never name a person.\
"""


def candidates() -> Select[int]:
    """ACLED events whose notes match and have no current verdict (none, or stale)."""
    u = UxsClassification
    return (
        select(Event.id)
        .join(Source, Source.id == Event.source_id)
        .outerjoin(u, u.event_id == Event.id)
        .where(
            Source.slug == SOURCE,
            Event.description.is_not(None),
            Event.description.op("~*")(CANDIDATE_PATTERN),
            or_(
                u.event_id.is_(None),
                (u.status != "batched")
                & ((u.notes_sha256 != current_notes_hash()) | (u.prompt_version != PROMPT_VERSION)),
            ),
        )
        .order_by(Event.event_date.desc(), Event.id)
    )


def _clear(ev: Event) -> None:
    ev.uxs_activity = ev.uxs_platform = None
    ev.uxs_missions = []
    ev.uxs_payloads = []


def clear_stale(session: Session) -> int:
    """Drop verdicts whose notes ACLED edited so they no longer match the pattern."""
    u = UxsClassification
    stale = list(
        session.scalars(
            select(u.event_id)
            .join(Event, Event.id == u.event_id)
            .where(
                u.status != "batched",
                u.notes_sha256 != current_notes_hash(),
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
        session.execute(delete(u).where(u.event_id.in_(stale)))
    return len(stale)


def _row(session: Session, event_id: int) -> UxsClassification:
    row = session.get(UxsClassification, event_id)
    if row is None:
        row = UxsClassification(event_id=event_id, notes_sha256="", status="batched")
        session.add(row)
    return row


def store(
    event_id: int, verdict: UxsVerdict, tokens: tuple[int, int], sent_hash: str | None = None
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
            log.warning("uxs verdict for event %d quoted text not in its notes", event_id)
            return "quarantined"
        row.status = "done"
        row.evidence = quote if verdict.uxs is not None else None
        if verdict.uxs is not None:
            ev.uxs_activity = verdict.uxs.activity
            ev.uxs_platform = verdict.uxs.platform
            ev.uxs_missions = list(dict.fromkeys(verdict.uxs.missions))
            ev.uxs_payloads = list(dict.fromkeys(verdict.uxs.payloads))
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
        session.execute(delete(UxsClassification).where(UxsClassification.event_id == event_id))


def _item(session: Session, event_id: int) -> llm_batch.BatchItem:
    ev = session.get_one(Event, event_id)
    return llm_batch.BatchItem(
        custom_id=f"event-{event_id}",
        document_id=event_id,  # the batch's item key; here an event id
        user=build_user(ev),
        provenance=Provenance(event_ids=(event_id,)),
    )


def batch_job() -> llm_batch.BatchJob[UxsVerdict]:
    def rebuild(event_id: int) -> llm_batch.BatchItem:
        with session_factory()() as session:
            return _item(session, event_id)

    def store_result(event_id: int, verdict: UxsVerdict, tokens: tuple[int, int]) -> None:
        store(event_id, verdict, tokens)

    return llm_batch.BatchJob(
        stage=STAGE,
        model=HAIKU,
        prompt_version=PROMPT_VERSION,
        system=SYSTEM,
        output_model=UxsVerdict,
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
        user=item.user, output_model=UxsVerdict, provenance=item.provenance,
        max_tokens=MAX_TOKENS, effort=EFFORT,
    )  # fmt: skip
    if not result.ok or result.parsed is None:
        _set_quarantined(event_id)
        return "quarantined"
    return store(event_id, result.parsed, (result.input_tokens, result.output_tokens), sent)


def run_uxs(limit: int = 50, gateway: Gateway | None = None) -> dict[str, int]:
    """Pipeline stage ``uxs``: collect finished batches, then classify what is queued."""
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
            log.warning("budget paused; uxs batch not submitted")
            out["batched"] = 0
        return out
    for event_id in ids:
        try:
            status = call_one(gateway, event_id)
        except BudgetPausedError:
            log.warning("budget paused; stopping the uxs pass")
            break
        out[status] = out.get(status, 0) + 1
    log.info("uxs pass: %s", out)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.enrich.acled_uxs")
    parser.add_argument("--sample", type=int, help="classify N candidates now and show them")
    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)
    if not args.sample:
        log.info("uxs pass: %s", run_uxs())
        return 0
    gateway = Gateway()
    with session_factory()() as session:
        ids = list(session.scalars(candidates().limit(args.sample)))
    for event_id in ids:
        status = call_one(gateway, event_id)
        with session_factory()() as session:
            ev = session.get_one(Event, event_id)
            row = session.get(UxsClassification, event_id)
            print(
                f"{ev.source_key} {status}: activity={ev.uxs_activity} "
                f"platform={ev.uxs_platform} missions={ev.uxs_missions} "
                f"payloads={ev.uxs_payloads} evidence={row.evidence if row else None!r}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

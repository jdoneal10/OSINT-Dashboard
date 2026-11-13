"""Haiku extraction: English summary + structured events, organizations and seizures.

Input: ``documents`` with ``pipeline_status='relevant'`` (news/press only; the gateway
refuses anything ACLED-derived). Output, all tagged with model + prompt_version + tokens:

- ``documents.translated_text`` <- English summary (ES->EN where needed)
- ``events`` (+ ``event_documents``) with geocoded points and ACLED-compatible event types
- ``seizures`` (+ ``seizure_documents``)
- ``actor_events`` (perpetrator / target) for named organizations only

Hard rule 3 (ADR 0005): the schema has NO fields for individuals. Only leaders of criminal
organizations, identified as such by the source, may be named, and only in free text
(summary, description, evidence); everyone else is described by role. Organizations named
after families (e.g. "Los Salazar") are organizations.

Re-running with a new ``PROMPT_VERSION`` replaces the document's derived records.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Mapping
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    Actor,
    ActorAlias,
    Document,
    Event,
    Label,
    Seizure,
    Source,
    actor_events,
    event_documents,
    seizure_documents,
)
from app.db.session import session_factory
from app.enrich.actors import ActorIndex
from app.enrich.geocode import geocode, in_aoi
from app.enrich.llm import batch as llm_batch
from app.enrich.llm.client import BudgetPausedError, Gateway, Provenance
from app.enrich.llm.pricing import HAIKU
from app.ingest.acled import RELIABILITY_CONFIDENCE
from app.reference.normalize import normalize_alias

log = logging.getLogger(__name__)

# v3: reported TCO leaders may be named in free text (ADR 0005)
# v4: smuggling and border-threat priority, border_threat field, threat-only rule (ADR 0007)
# v5: relevance boundaries (South America/Caribbean out; border-crossing context in)
PROMPT_VERSION = "extract-v5"
MAX_TEXT_CHARS = 30_000

EventType = Literal[
    "Battles",
    "Violence against civilians",
    "Explosions/Remote violence",
    "Riots",
    "Protests",
    "Strategic developments",
]
OrgType = Literal["cartel", "gang", "faction", "armed_group", "government", "other"]


BorderThreat = Literal[
    "human_smuggling",
    "uas_incursion",
    "laser_strike",
    "gunfire",
    "assault_on_personnel",
    "tunnel",
    "other_border_threat",
]


class Location(BaseModel):
    place: str | None = Field(description="Town, neighborhood or landmark, as written")
    municipality: str | None
    state: str | None
    country: str | None = Field(description="Country name in English")


class ExtractedEvent(BaseModel):
    event_type: EventType
    sub_event_type: str | None = Field(description="Short label, e.g. 'Armed clash'")
    event_date: str | None = Field(description="YYYY-MM-DD if stated or inferable, else null")
    date_precision: Literal["day", "week", "month", "unknown"]
    location: Location
    fatalities: int | None = Field(ge=0)
    injured: int | None = Field(ge=0)
    perpetrators: list[str] = Field(description="Organizations or groups, never people")
    targets: list[str] = Field(description="Organizations or groups, never people")
    description: str = Field(
        description="One or two English sentences; name only reported criminal-group leaders"
    )
    evidence: str = Field(description="Short supporting quote (<= 200 chars) from the text")
    border_threat: BorderThreat | None = Field(description="Priority border-threat category")


class ExtractedSeizure(BaseModel):
    seizure_date: str | None = Field(description="YYYY-MM-DD or null")
    location: Location
    substance: str = Field(description="e.g. fentanyl, methamphetamine, cocaine, weapons, cash")
    chemicals: list[str] = Field(description="Precursor or essential chemicals named, if any")
    quantity: float | None = Field(ge=0)
    unit: Literal["kg", "lb", "g", "l", "units", "pills", "other"] | None
    seizing_agency: str | None = Field(description="Agency or force, not a person")
    description: str


class ExtractedOrganization(BaseModel):
    name: str
    org_type: OrgType


class Extraction(BaseModel):
    relevant: bool = Field(description="False if the article is not about organized crime")
    summary_en: str = Field(
        description="English summary, 2-4 sentences; name only reported criminal-group leaders"
    )
    events: list[ExtractedEvent] = Field(max_length=10)
    seizures: list[ExtractedSeizure] = Field(max_length=10)
    organizations: list[ExtractedOrganization] = Field(max_length=20)


RULES = """You extract structured intelligence from news articles and official press releases \
(Spanish or English) about transnational criminal organizations in Mexico, Central America and \
the U.S. Southwest border. The output feeds an analyst's database; precision matters more \
than coverage. TOP PRIORITY: human smuggling, and threats to the U.S.-Mexico border such as \
criminal drone (UAS) incursions, laser strikes, gunfire at or across the border, attacks on \
border personnel, and cross-border tunnels.

RULES
1. People. The only individuals you may name are leaders of criminal organizations whom the \
text itself identifies as leaders (e.g. "CJNG leader Rafael Alvarez Ayala, alias R2"), and \
only in summary_en, description and evidence, using the name and alias as the text gives \
them. Never name anyone else: victims, relatives, bystanders, suspects or defendants not \
described as leaders, journalists, or public officials. Refer to them by role ("two \
victims", "a municipal police officer", "Mexico's Security Secretary"); if a quote would \
name such a person, choose another quote. Never put a person in perpetrators, targets or \
organizations; those lists hold organizations only. Organizations whose names include a \
surname (e.g. "Los Salazar") are organizations.
2. Extract only what the text states. Do not infer fatalities, dates or locations that are \
not supported. Use null when unknown. "evidence" must be a short quote from the text.
3. One event per distinct incident (place + time). Background, history and statistics are \
not events. Court cases, arrests, extraditions, sanctions and policy decisions are \
"Strategic developments".
4. Event types (use exactly these):
   - Battles: armed clashes between organized groups, or between a group and security forces.
   - Violence against civilians: killings, kidnappings, disappearances, torture, attacks or \
threats against unarmed people, including bodies found with signs of violence.
   - Explosions/Remote violence: bombs, IEDs, drones, grenades, arson attacks.
   - Riots: violent demonstrations, lynchings, prison riots.
   - Protests: peaceful demonstrations.
   - Strategic developments: arrests, seizures without violence, lab discoveries, \
designations, indictments, extraditions, truces, territory changes without fighting.
5. Seizures: one entry per seizure of drugs, precursor chemicals, weapons or cash, with the \
quantity and unit as written (convert words to numbers). Laboratories count as seizures only \
if materials were seized.
6. Organizations: list each criminal organization, faction, gang or armed group named, and \
any government force (e.g. SEMAR, Guardia Nacional, CBP). Use the canonical name from the \
KNOWN ORGANIZATIONS list when the text refers to one of them by an alias.
7. Relevance. Set "relevant" to true when the article is about any of: organized-crime \
activity in Mexico, Central America or the U.S. border region; human smuggling or migrant \
smuggling; threats to the border (rule 9); actions against criminal groups operating in the \
region (arrests, prosecutions, extraditions, sanctions, designations), wherever they happen; \
seizures of drugs, precursors, weapons or cash linked to the region; or U.S.-Mexico border \
context: border-security policy, crossing and port-of-entry developments (closures, customs \
cooperation, trade-fraud enforcement) and official border enforcement statistics (context \
only: no events, see rule 10). Set it to false, with empty lists, for: ordinary politics, \
business, sport or entertainment; crime with no organized-crime or border link, including \
sexual exploitation or fraud by individuals or networks not tied to cartels or smuggling; \
and crime in South America, the Caribbean or elsewhere unless the article ties it to \
Mexico, Central America or the U.S. border (country profiles of those places too).
8. "summary_en" is always in English.
9. border_threat. For each event, set border_threat to one of: human_smuggling (smuggling \
loads, stash houses, smuggling deaths, smuggling organizations and their prosecution), \
uas_incursion (criminal drones crossing or operating at the border), laser_strike (lasers \
aimed at aircraft or border personnel), gunfire (shots fired at or across the border), \
assault_on_personnel (attacks on border officers or soldiers), tunnel (cross-border \
tunnels), other_border_threat (another criminal threat at the border); otherwise null.
10. Threat activity only. Describe what the criminal actors did, where (city, municipality \
or port, as the text gives it, never finer), when, and the outcome. NEVER record the number, \
units, equipment, positions, patrol patterns or response tactics of U.S. or Mexican \
personnel, or the locations of sensors, cameras or towers; leave such details out of \
description and evidence too. An article that only describes law-enforcement or military \
operations, deployments, closures or training produces no events: summarize it in \
summary_en only."""


def build_system(session: Session) -> str:
    """Deterministic instruction block (cached prefix): rules + known organization aliases."""
    rows = session.execute(
        select(Actor.canonical_name, func.array_agg(ActorAlias.alias))
        .join(ActorAlias, ActorAlias.actor_id == Actor.id)
        .where(Actor.actor_type.in_(["tco", "faction"]))
        .group_by(Actor.canonical_name)
        .order_by(Actor.canonical_name)
    ).all()
    lines = []
    for canonical, aliases in rows:
        others = sorted({a for a in aliases if a and a != canonical})
        lines.append(f"- {canonical}" + (f" (also: {'; '.join(others)})" if others else ""))
    return RULES + "\n\nKNOWN ORGANIZATIONS\n" + "\n".join(lines)


def build_user(doc: Document, source_name: str) -> str:
    published = doc.published_at.date().isoformat() if doc.published_at else "unknown"
    body = doc.original_text or doc.summary or ""
    return (
        f"SOURCE: {source_name}\nPUBLISHED: {published}\nURL: {doc.source_url or ''}\n"
        f"TITLE: {doc.title or ''}\n\nTEXT:\n{body[:MAX_TEXT_CHARS]}"
    )


# --------------------------------------------------------------------------- storing


def _date(value: str | None, fallback: dt.date) -> tuple[dt.date, bool]:
    try:
        return (dt.date.fromisoformat(value), True) if value else (fallback, False)
    except ValueError:
        return fallback, False


_PRECISION = {"day": 1, "week": 2, "month": 3, "unknown": 3}
_LINKABLE = {"cartel", "gang", "faction", "armed_group"}


def _actor_ids(
    index: ActorIndex,
    names: list[str],
    org_types: Mapping[str, str],
    citation: dict[str, str],
) -> list[int]:
    """Known actors by alias; unknown names only if extracted as a criminal organization."""
    out: list[int] = []
    for name in names:
        hit = index.match(name)
        if hit is None and org_types.get(normalize_alias(name)) in _LINKABLE:
            hit = index.create(name, name, "armed_group", citation=citation)
        if hit is not None and hit not in out:
            out.append(hit)
    return out


def store_extraction(
    session: Session, doc: Document, ex: Extraction, *, model: str, tokens: tuple[int, int]
) -> dict[str, int]:
    source = session.get_one(Source, doc.source_id)
    confidence: Decimal | None = RELIABILITY_CONFIDENCE.get(source.reliability)
    fallback_date = (doc.published_at or doc.retrieved_at).date()
    now = dt.datetime.now(dt.UTC)
    llm = {
        "llm_model": model,
        "prompt_version": PROMPT_VERSION,
        "llm_input_tokens": tokens[0],
        "llm_output_tokens": tokens[1],
    }
    prefix = f"doc{doc.id}:"
    # Replace earlier derived records for this document (prompt version changes).
    session.execute(
        delete(Event).where(Event.source_id == doc.source_id, Event.source_key.like(prefix + "%"))
    )
    session.execute(
        delete(Seizure).where(
            Seizure.source_id == doc.source_id, Seizure.source_key.like(prefix + "%")
        )
    )
    doc.translated_text = ex.summary_en
    for k, v in llm.items():
        setattr(doc, k, v)
    doc.pipeline_status = "extracted" if ex.relevant else "filtered_out"
    if not ex.relevant:
        return {"events": 0, "seizures": 0}

    citation = {"title": doc.title or "news article", "publisher": source.name,
                "url": doc.source_url or ""}  # fmt: skip
    org_types = {normalize_alias(o.name): o.org_type for o in ex.organizations}
    index = ActorIndex.load(session)
    for i, e in enumerate(ex.events):
        when, exact = _date(e.event_date, fallback_date)
        geo = geocode(session, place=e.location.place, municipality=e.location.municipality,
                      state=e.location.state, country=e.location.country)  # fmt: skip
        ev = Event(
            source_id=doc.source_id,
            source_key=f"{prefix}e{i}",
            source_url=doc.source_url,
            retrieved_at=now,
            confidence=confidence,
            event_date=when,
            event_type=e.event_type,
            sub_event_type=e.sub_event_type,
            description=e.description,
            fatalities=e.fatalities,
            geom=func.ST_GeogFromText(geo.ewkt) if geo else None,
            country_iso3=geo.country_iso3 if geo else None,
            in_aoi=in_aoi(e.location.country, e.location.state),
            border_threat=e.border_threat,
            admin1_code=geo.admin1_code if geo else None,
            admin2_code=geo.admin2_code if geo else None,
            admin1_name=e.location.state,
            admin2_name=e.location.municipality,
            location_name=e.location.place,
            geo_precision=geo.precision if geo else None,
            time_precision=_PRECISION[e.date_precision] if exact else 3,
            attributes={
                "perpetrators": e.perpetrators,
                "targets": e.targets,
                "injured": e.injured,
                "evidence": e.evidence,
                "location": e.location.model_dump(),
                "geocode_match": geo.matched if geo else None,
            },
            **llm,
        )
        session.add(ev)
        session.flush()
        session.execute(event_documents.insert().values(event_id=ev.id, document_id=doc.id))
        for role, names in (("perpetrator", e.perpetrators), ("target", e.targets)):
            for actor_id in _actor_ids(index, names, org_types, citation):
                session.execute(
                    actor_events.insert().values(actor_id=actor_id, event_id=ev.id, role=role)
                )
    for i, s in enumerate(ex.seizures):
        when, _ = _date(s.seizure_date, fallback_date)
        geo = geocode(session, place=s.location.place, municipality=s.location.municipality,
                      state=s.location.state, country=s.location.country)  # fmt: skip
        sz = Seizure(
            source_id=doc.source_id,
            source_key=f"{prefix}s{i}",
            source_url=doc.source_url,
            retrieved_at=now,
            confidence=confidence,
            seizure_date=when,
            geom=func.ST_GeogFromText(geo.ewkt) if geo else None,
            substance=s.substance,
            chemical_class=", ".join(s.chemicals)[:64] or None,
            quantity=Decimal(str(s.quantity)) if s.quantity is not None else None,
            unit=s.unit,
            seizing_agency=s.seizing_agency,
            node_id=geo.node_id if geo else None,
            country_iso3=geo.country_iso3 if geo else None,
            in_aoi=in_aoi(s.location.country, s.location.state),
            admin1_code=geo.admin1_code if geo else None,
            **llm,
        )
        session.add(sz)
        session.flush()
        session.execute(seizure_documents.insert().values(seizure_id=sz.id, document_id=doc.id))
    return {"events": len(ex.events), "seizures": len(ex.seizures)}


MAX_TOKENS = 8000
EFFORT = "low"


def _item(session: Session, doc_id: int) -> llm_batch.BatchItem:
    doc = session.get_one(Document, doc_id)
    source_name = session.get_one(Source, doc.source_id).name
    return llm_batch.BatchItem(
        custom_id=f"doc-{doc_id}",
        document_id=doc_id,
        user=build_user(doc, source_name),
        provenance=Provenance(document_ids=(doc_id,)),
    )


def _store(doc_id: int, parsed: Extraction, tokens: tuple[int, int]) -> dict[str, int]:
    with session_factory()() as session, session.begin():
        doc = session.get_one(Document, doc_id)
        return store_extraction(session, doc, parsed, model=HAIKU, tokens=tokens)


def _set_status(doc_id: int, status: str) -> None:
    with session_factory()() as session, session.begin():
        session.get_one(Document, doc_id).pipeline_status = status


def batch_job(system: str) -> llm_batch.BatchJob[Extraction]:
    """Extraction as a Message Batches job (backlogs; see app.enrich.llm.batch)."""

    def rebuild(doc_id: int) -> llm_batch.BatchItem:
        with session_factory()() as session:
            return _item(session, doc_id)

    def store(doc_id: int, parsed: Extraction, tokens: tuple[int, int]) -> None:
        _store(doc_id, parsed, tokens)

    return llm_batch.BatchJob(
        stage="extract",
        model=HAIKU,
        prompt_version=PROMPT_VERSION,
        system=system,
        output_model=Extraction,
        max_tokens=MAX_TOKENS,
        effort=EFFORT,
        rebuild=rebuild,
        store=store,
        fail=lambda doc_id: _set_status(doc_id, "quarantined"),
        requeue=lambda doc_id: _set_status(doc_id, "relevant"),
    )


def submit_batch(gateway: Gateway, ids: list[int], system: str) -> int:
    """Send ``ids`` through the Batch API; mark the submitted documents 'batched'."""
    with session_factory()() as session:
        items = [_item(session, doc_id) for doc_id in ids]
    row = llm_batch.submit(gateway, batch_job(system), items)
    if row is None:
        return 0
    with session_factory()() as session, session.begin():
        for doc_id in row.items.values():
            session.get_one(Document, int(doc_id)).pipeline_status = "batched"
    return row.n_requests


def run_collect(gateway: Gateway | None = None) -> dict[str, int]:
    """Store results of finished extraction batches (pipeline stage ``collect``)."""
    gateway = gateway or Gateway()
    with session_factory()() as session:
        system = build_system(session)
    return llm_batch.collect(gateway, {"extract": batch_job(system)})


def run_extract(limit: int = 50, gateway: Gateway | None = None) -> dict[str, int]:
    """Extract relevant documents: real-time for a normal run, the Batch API for a backlog.

    A backlog of at least ``llm_batch_threshold`` documents (a backfill, or re-extraction
    after a prompt change) is submitted as one batch at half price; results are stored by
    the ``collect`` stage when the batch ends.
    """
    gateway = gateway or Gateway()
    settings = get_settings()
    counts = {"extracted": 0, "not_relevant": 0, "quarantined": 0, "events": 0, "seizures": 0}
    relevant = (
        select(Document.id)
        .where(Document.pipeline_status == "relevant")
        .order_by(Document.published_at.desc().nulls_last(), Document.id)
    )
    with session_factory()() as session:
        system = build_system(session)
        backlog = session.scalar(select(func.count()).select_from(relevant.subquery())) or 0
        if backlog >= settings.llm_batch_threshold:
            ids = list(session.scalars(relevant.limit(settings.llm_batch_max_requests)))
        else:
            ids = list(session.scalars(relevant.limit(limit)))
    if backlog >= settings.llm_batch_threshold:
        try:
            batched = submit_batch(gateway, ids, system)
        except BudgetPausedError:
            log.warning("budget paused; extraction batch not submitted")
            batched = 0
        log.info("extraction: backlog %d -> %d submitted as a batch", backlog, batched)
        return {"batched": batched}
    for doc_id in ids:
        with session_factory()() as session:
            user = _item(session, doc_id).user
        try:
            result = gateway.call(
                stage="extract",
                model=HAIKU,
                prompt_version=PROMPT_VERSION,
                system=system,
                user=user,
                output_model=Extraction,
                provenance=Provenance(document_ids=(doc_id,)),
                max_tokens=MAX_TOKENS,
                effort=EFFORT,
            )
        except BudgetPausedError:
            log.warning("budget paused; stopping extraction")
            break
        if not result.ok or result.parsed is None:
            _set_status(doc_id, "quarantined")
            counts["quarantined"] += 1
            continue
        stored = _store(doc_id, result.parsed, (result.input_tokens, result.output_tokens))
        counts["extracted" if result.parsed.relevant else "not_relevant"] += 1
        counts["events"] += stored["events"]
        counts["seizures"] += stored["seizures"]
    log.info("extraction: %s", counts)
    return counts


def mark_for_reextraction() -> int:
    """Queue documents Haiku processed under an older prompt version (a backfill; batched).

    Covers documents it extracted and documents it judged not relevant. Documents whose
    records the owner has labeled are skipped: re-extraction would replace those records,
    and their labels must keep judging the version they were made on.
    """
    labeled = select(Label.document_id).where(Label.target_table.in_(("events", "seizures")))
    with session_factory()() as session, session.begin():
        docs = session.scalars(
            select(Document).where(
                Document.pipeline_status.in_(("extracted", "filtered_out")),
                Document.prompt_version.is_not(None),  # Haiku has seen it
                Document.prompt_version != PROMPT_VERSION,
                Document.id.not_in(labeled),
            )
        ).all()
        for doc in docs:
            doc.pipeline_status = "relevant"
        return len(docs)


def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415 — CLI only

    parser = argparse.ArgumentParser(prog="python -m app.enrich.extract")
    parser.add_argument(
        "--reextract",
        action="store_true",
        help=f"queue documents extracted under a prompt other than {PROMPT_VERSION}",
    )
    args = parser.parse_args(argv)
    if args.reextract:
        print(f"Queued {mark_for_reextraction()} document(s); the pipeline batches them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

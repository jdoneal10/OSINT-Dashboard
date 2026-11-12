"""Haiku extraction: English summary + structured events, organizations and seizures.

Input: ``documents`` with ``pipeline_status='relevant'`` (news/press only; the gateway
refuses anything ACLED-derived). Output, all tagged with model + prompt_version + tokens:

- ``documents.translated_text`` <- English summary (ES->EN where needed)
- ``events`` (+ ``event_documents``) with geocoded points and ACLED-compatible event types
- ``seizures`` (+ ``seizure_documents``)
- ``actor_events`` (perpetrator / target) for named organizations only

Hard rule 3: the schema has NO fields for individuals and the prompt forbids naming people;
organizations named after families (e.g. "Los Salazar") are organizations.

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

from app.db.models import (
    Actor,
    ActorAlias,
    Document,
    Event,
    Seizure,
    Source,
    actor_events,
    event_documents,
    seizure_documents,
)
from app.db.session import session_factory
from app.enrich.actors import ActorIndex
from app.enrich.geocode import geocode
from app.enrich.llm.client import BudgetPausedError, Gateway, Provenance
from app.enrich.llm.pricing import HAIKU
from app.ingest.acled import RELIABILITY_CONFIDENCE
from app.reference.normalize import normalize_alias

log = logging.getLogger(__name__)

PROMPT_VERSION = "extract-v1"
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
    description: str = Field(description="One or two English sentences, no personal names")
    evidence: str = Field(description="Short supporting quote (<= 200 chars) from the text")


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
    summary_en: str = Field(description="English summary, 2-4 sentences, no personal names")
    events: list[ExtractedEvent] = Field(max_length=10)
    seizures: list[ExtractedSeizure] = Field(max_length=10)
    organizations: list[ExtractedOrganization] = Field(max_length=20)


RULES = """You extract structured intelligence from news articles and official press releases \
(Spanish or English) about transnational criminal organizations in Mexico, Central America and \
the U.S. Southwest border. The output feeds an analyst's database; precision matters more \
than coverage.

RULES
1. Never output the name of an individual person anywhere. Refer to people by role \
("a municipal police officer", "a suspected cell leader", "two victims"). Organizations whose \
names include a surname (e.g. "Los Salazar") are organizations and may be named.
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
7. Set "relevant" to false and leave the lists empty if the article is not actually about \
organized crime in the region.
8. "summary_en" is always in English."""


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
            country_iso3="MEX" if geo else None,
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
            country_iso3="MEX" if geo else None,
            admin1_code=geo.admin1_code if geo else None,
            **llm,
        )
        session.add(sz)
        session.flush()
        session.execute(seizure_documents.insert().values(seizure_id=sz.id, document_id=doc.id))
    return {"events": len(ex.events), "seizures": len(ex.seizures)}


def run_extract(limit: int = 50, gateway: Gateway | None = None) -> dict[str, int]:
    gateway = gateway or Gateway()
    counts = {"extracted": 0, "not_relevant": 0, "quarantined": 0, "events": 0, "seizures": 0}
    with session_factory()() as session:
        system = build_system(session)
        ids = list(
            session.scalars(
                select(Document.id)
                .where(Document.pipeline_status == "relevant")
                .order_by(Document.published_at.desc().nulls_last(), Document.id)
                .limit(limit)
            )
        )
    for doc_id in ids:
        with session_factory()() as session:
            doc = session.get_one(Document, doc_id)
            source_name = session.get_one(Source, doc.source_id).name
            user = build_user(doc, source_name)
        try:
            result = gateway.call(
                stage="extract",
                model=HAIKU,
                prompt_version=PROMPT_VERSION,
                system=system,
                user=user,
                output_model=Extraction,
                provenance=Provenance(document_ids=(doc_id,)),
                max_tokens=8000,
                effort="low",
            )
        except BudgetPausedError:
            log.warning("budget paused; stopping extraction")
            break
        with session_factory()() as session, session.begin():
            doc = session.get_one(Document, doc_id)
            if not result.ok or result.parsed is None:
                doc.pipeline_status = "quarantined"
                counts["quarantined"] += 1
                continue
            stored = store_extraction(
                session, doc, result.parsed, model=HAIKU,
                tokens=(result.input_tokens, result.output_tokens),
            )  # fmt: skip
            counts["extracted" if result.parsed.relevant else "not_relevant"] += 1
            counts["events"] += stored["events"]
            counts["seizures"] += stored["seizures"]
    log.info("extraction: %s", counts)
    return counts

"""U.S. designations: OFAC SDN list and State Department FTO/SDGT notices (Federal Register).

Hard rule 3: individuals on the SDN list are stored ONLY as the published name and programs,
as an attribute of the designation record (``listed_parties``). No dates of birth, ID numbers,
addresses or other personal details are kept, and individuals are never linked to actors or
turned into records of their own. Entities are linked to ``actors`` by alias.

SDN entries carry no designation date in the XML, so ``action_date`` is the publish date of
the first list in which this project saw the entry (``attributes.date_basis``). Entries that
disappear later get a separate ``removed`` record.

    python -m app.ingest designations
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Boolean, delete, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import ActorAlias, Designation, designation_actors
from app.db.session import session_factory
from app.ingest.http import PoliteClient
from app.ingest.raw import sha256_bytes, write_raw
from app.ingest.runs import ingest_run, last_successful_params, source_id
from app.reference.normalize import normalize_alias

log = logging.getLogger(__name__)

SDN_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.XML"
SDN_DETAIL = "https://sanctionssearch.ofac.treas.gov/Details.aspx?id={uid}"
FR_API = "https://www.federalregister.gov/api/v1/documents.json"
FR_SINCE = dt.date(2025, 1, 1)  # Mexican cartels were first designated FTOs in 2025

PROGRAMS = frozenset({"SDNTK", "ILLICIT-DRUGS-EO14059", "TCO", "SDGT", "FTO"})
# Mexico (Phase 2) and the Central American corridor (Phase 4).
NEXUS_COUNTRIES = frozenset(
    {"Mexico", "Guatemala", "Belize", "Honduras", "El Salvador", "Nicaragua", "Costa Rica",
     "Panama"}
)  # fmt: skip


# --------------------------------------------------------------------------- OFAC SDN


@dataclass
class SdnEntry:
    uid: str
    name: str
    sdn_type: str  # Entity | Individual | Vessel | Aircraft
    programs: list[str]
    countries: set[str]
    aliases: list[str] = field(default_factory=list)  # entities only


def parse_sdn(content: bytes) -> tuple[dt.date, list[SdnEntry]]:
    root = ET.fromstring(content)  # noqa: S314 — trusted government source, no DTD
    ns = {"s": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {"s": ""}
    q = (lambda tag: f"s:{tag}") if ns["s"] else (lambda tag: tag)
    publish_text = root.findtext(f".//{q('publshInformation')}/{q('Publish_Date')}", namespaces=ns)
    publish = dt.datetime.strptime(publish_text or "", "%m/%d/%Y").date()  # noqa: DTZ007
    entries = []
    for e in root.findall(q("sdnEntry"), ns):
        programs = [p.text or "" for p in e.findall(f"{q('programList')}/{q('program')}", ns)]
        countries = {
            a.findtext(q("country"), namespaces=ns) or ""
            for a in e.findall(f"{q('addressList')}/{q('address')}", ns)
        }
        if not (PROGRAMS & set(programs)) or not (NEXUS_COUNTRIES & countries):
            continue
        sdn_type = e.findtext(q("sdnType"), namespaces=ns) or ""
        last = (e.findtext(q("lastName"), namespaces=ns) or "").strip()
        first = (e.findtext(q("firstName"), namespaces=ns) or "").strip()
        name = f"{last}, {first}" if first else last
        aliases: list[str] = []
        if sdn_type == "Entity":
            aliases = [
                (a.findtext(q("lastName"), namespaces=ns) or "").strip()
                for a in e.findall(f"{q('akaList')}/{q('aka')}", ns)
            ]
        entries.append(
            SdnEntry(
                uid=e.findtext(q("uid"), namespaces=ns) or "",
                name=name,
                sdn_type=sdn_type,
                programs=sorted(programs),
                countries=countries & NEXUS_COUNTRIES,
                aliases=[a for a in aliases if a],
            )
        )
    return publish, entries


def listed_party(entry: SdnEntry) -> dict[str, Any]:
    """The only data kept about a listed party. Individuals: name and type, nothing else."""
    if entry.sdn_type == "Individual":
        return {"name": entry.name, "type": "individual"}
    return {"name": entry.name, "type": entry.sdn_type.lower(), "aliases": entry.aliases}


# --------------------------------------------------------------------------- actor links


def _alias_index(session: Session) -> dict[str, int]:
    return dict(session.execute(select(ActorAlias.alias_normalized, ActorAlias.actor_id)).all())


def link_actors(session: Session, designation_id: int, names: list[str]) -> int:
    index = _alias_index(session)
    actor_ids = {index[k] for n in names if (k := normalize_alias(n)) in index}
    for actor_id in actor_ids:
        session.execute(
            insert(designation_actors)
            .values(designation_id=designation_id, actor_id=actor_id)
            .on_conflict_do_nothing()
        )
    return len(actor_ids)


def _upsert_designation(session: Session, values: dict[str, Any]) -> tuple[int, bool]:
    base = insert(Designation).values(**values)
    keep_first_seen = {"action_date", "source_id", "source_key"}
    stmt = base.on_conflict_do_update(
        constraint="uq_designations_source_key",
        set_={k: base.excluded[k] for k in values if k not in keep_first_seen}
        | {"updated_at": func.now()},
    ).returning(Designation.id, literal_column("(xmax = 0)", Boolean))
    row = session.execute(stmt).one()
    return row[0], bool(row[1])


# --------------------------------------------------------------------------- jobs


def run_ofac(client: PoliteClient) -> None:
    last = last_successful_params("designations-ofac") or {}
    with ingest_run("designations-ofac", source_slug="ofac") as run:
        headers = {"If-None-Match": last["etag"]} if last.get("etag") else {}
        resp = client.get(SDN_URL, headers=headers)
        if resp.status_code == 304:
            run.params |= {"etag": last["etag"], "unchanged": True}
            return
        resp.raise_for_status()
        content = resp.content
        run.params["etag"] = resp.headers.get("ETag")
        run.params["sha256"] = sha256_bytes(content)
        if last.get("sha256") == run.params["sha256"]:
            run.params["unchanged"] = True
            return
        run.raw_paths.append(str(write_raw("ofac", run.id, "SDN.XML", content).path))
        publish, entries = parse_sdn(content)
        run.params |= {"publish_date": publish.isoformat(), "matched": len(entries)}
        now = dt.datetime.now(dt.UTC)
        with session_factory()() as session, session.begin():
            sid = source_id(session, "ofac")
            current = set()
            for entry in entries:
                key = f"sdn:{entry.uid}"
                current.add(key)
                values = {
                    "source_id": sid,
                    "source_key": key,
                    "source_url": SDN_DETAIL.format(uid=entry.uid),
                    "retrieved_at": now,
                    "confidence": None,
                    "designation_type": "sdn",
                    "program": ";".join(entry.programs)[:64],
                    "action": "listed",
                    "action_date": publish,
                    "title": entry.name if entry.sdn_type != "Individual" else "SDN listing",
                    "listed_parties": [listed_party(entry)],
                }
                designation_id, inserted = _upsert_designation(session, values)
                run.inserted += int(inserted)
                run.updated += int(not inserted)
                if entry.sdn_type == "Entity":
                    link_actors(session, designation_id, [entry.name, *entry.aliases])
            previous = set(
                session.scalars(
                    select(Designation.source_key).where(
                        Designation.source_id == sid, Designation.action == "listed"
                    )
                )
            )
            removed_already = {
                k.split(":removed:")[0]
                for k in session.scalars(
                    select(Designation.source_key).where(
                        Designation.source_id == sid, Designation.action == "removed"
                    )
                )
            }
            for key in sorted(previous - current - removed_already):
                listed = session.scalars(
                    select(Designation).where(
                        Designation.source_id == sid, Designation.source_key == key
                    )
                ).one()
                _upsert_designation(
                    session,
                    {
                        "source_id": sid,
                        "source_key": f"{key}:removed:{publish.isoformat()}",
                        "source_url": listed.source_url,
                        "retrieved_at": now,
                        "confidence": None,
                        "designation_type": "sdn",
                        "program": listed.program,
                        "action": "removed",
                        "action_date": publish,
                        "title": listed.title,
                        "listed_parties": listed.listed_parties,
                    },
                )
                run.deleted += 1


_TITLE_NAMES = re.compile(r"\bDesignations? of (?P<names>.+?)(?: as (?:a |an )?\w.*)?$", re.I)


def names_from_title(title: str) -> list[str]:
    """'Foreign Terrorist Organization Designations of A, B, and C' -> ['A', 'B', 'C']."""
    m = _TITLE_NAMES.search(title)
    if not m:
        return []
    text = m.group("names")
    text = re.sub(r",?\s+and\s+", ", ", text)
    return [n.strip(" .") for n in text.split(",") if n.strip(" .")]


# FR returns every State FTO/SDGT notice worldwide. Keep notices about TCOs in or operating
# through Mexico and Central America: any listed name that resolves to a known actor, or a
# title naming one of these regional groups. Everything else is out of scope (not stored).
REGIONAL_TCO = re.compile(
    r"c[aá]rtel|mara salvatrucha|ms-13|barrio 18|tren de aragua|viagras|familia michoacana",
    re.IGNORECASE,
)


def in_scope(session: Session, title: str, names: list[str]) -> bool:
    if REGIONAL_TCO.search(title):
        return True
    index = _alias_index(session)
    return any(normalize_alias(n) in index for n in names)


def _fr_type(title: str) -> str:
    return "fto" if "foreign terrorist organization" in title.lower() else "sdgt"


def _fr_action(title: str) -> str:
    lowered = title.lower()
    if "revocation" in lowered:
        return "revoked"
    if "amendment" in lowered:
        return "amended"
    return "designated"


def run_federal_register(client: PoliteClient) -> None:
    with ingest_run("designations-fr", source_slug="federal-register") as run:
        params: list[tuple[str, str]] = [
            ("conditions[agencies][]", "state-department"),
            ("conditions[type][]", "NOTICE"),
            ("conditions[publication_date][gte]", FR_SINCE.isoformat()),
            (
                "conditions[term]",
                '"Foreign Terrorist Organization" | "Specially Designated Global Terrorist"',
            ),
            ("per_page", "100"),
            ("order", "oldest"),
            *[
                ("fields[]", f)
                for f in ("title", "publication_date", "document_number", "html_url")
            ],
        ]
        resp = client.get(FR_API, params=params, crawl=False)
        resp.raise_for_status()
        run.raw_paths.append(
            str(write_raw("federal-register", run.id, "fto.json", resp.content).path)
        )
        results = resp.json().get("results") or []
        now = dt.datetime.now(dt.UTC)
        with session_factory()() as session, session.begin():
            sid = source_id(session, "federal-register")
            for doc in results:
                title = doc["title"]
                names = names_from_title(title)
                if not names or not in_scope(session, title, names):
                    # Not a designation notice, or outside the AOI: drop any copy stored
                    # under an earlier, broader filter so scope changes are self-healing.
                    session.execute(
                        delete(Designation).where(
                            Designation.source_id == sid,
                            Designation.source_key == doc["document_number"],
                        )
                    )
                    run.params["out_of_scope"] = run.params.get("out_of_scope", 0) + 1
                    continue
                designation_id, inserted = _upsert_designation(
                    session,
                    {
                        "source_id": sid,
                        "source_key": doc["document_number"],
                        "source_url": doc["html_url"],
                        "retrieved_at": now,
                        "confidence": None,
                        "designation_type": _fr_type(title),
                        "program": "INA 219" if _fr_type(title) == "fto" else "EO 13224",
                        "action": _fr_action(title),
                        "action_date": dt.date.fromisoformat(doc["publication_date"]),
                        "title": title,
                        "listed_parties": [{"name": n, "type": "organization"} for n in names],
                    },
                )
                run.inserted += int(inserted)
                run.updated += int(not inserted)
                link_actors(session, designation_id, names)
        run.params["notices"] = len(results)


def run_designations(client: PoliteClient | None = None) -> int:
    owns = client is None
    client = client or PoliteClient(min_interval=1.0, timeout=120)
    failures = 0
    try:
        for job in (run_federal_register, run_ofac):
            try:
                job(client)
            except Exception:
                failures += 1
                log.exception("%s failed (recorded in ingest_runs)", job.__name__)
    finally:
        if owns:
            client.close()
    return 1 if failures == 2 else 0

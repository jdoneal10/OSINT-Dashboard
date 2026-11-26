"""Bring stored person records up to ADR 0013 amendment 1 (idempotent; no model calls).

``uv run python -m app.enrich.person_repair`` reports what would change; ``--apply`` writes.
It corrects names the cited text lacks, removes family details and unsupported aliases,
withholds unsafe quotes and recomputes match keys. It never deletes, merges or splits a
person and never touches labels. The report masks U.S. persons.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, Person, PersonAttribute, PersonEvent, PersonOrganization
from app.db.session import session_factory
from app.enrich import person_guard
from app.enrich.extract import shown_text
from app.enrich.persons import name_key

CLAIM_TABLES: tuple[type[PersonAttribute | PersonOrganization | PersonEvent], ...] = (
    PersonAttribute,
    PersonOrganization,
    PersonEvent,
)


@dataclass
class Report:
    names: list[tuple[int, str]] = field(default_factory=list)
    unresolved: list[int] = field(default_factory=list)
    titles: list[int] = field(default_factory=list)
    aliases: list[int] = field(default_factory=list)
    quotes: list[int] = field(default_factory=list)
    keys: list[int] = field(default_factory=list)


def repair(session: Session) -> Report:
    report = Report()
    people = {p.id: p for p in session.scalars(select(Person).order_by(Person.id))}
    rows = list(session.scalars(select(PersonAttribute).order_by(PersonAttribute.id)))
    by_person: dict[int, list[PersonAttribute]] = defaultdict(list)
    listed: dict[int | None, list[str]] = defaultdict(list)
    for a in rows:
        by_person[a.person_id].append(a)
        if a.attribute == "alias":
            listed[a.document_id].append(a.value)
    doc_ids = {a.document_id for a in rows if a.document_id is not None}
    texts = {
        d.id: shown_text(d)
        for d in session.scalars(select(Document).where(Document.id.in_(doc_ids)))
    }

    _fix_names(people, by_person, texts, report)
    for a in rows:  # the corrected names are the ones a quote may use
        if a.attribute == "role":
            listed[a.document_id].append(people[a.person_id].display_name)
    _fix_claims(session, rows, texts, report)
    session.flush()
    _fix_quotes(session, listed, report)
    session.flush()
    return report


def _fix_names(
    people: dict[int, Person],
    by_person: dict[int, list[PersonAttribute]],
    texts: dict[int, str],
    report: Report,
) -> None:
    for pid, person in people.items():
        docs = sorted({a.document_id for a in by_person[pid] if a.document_id in texts})
        aliases = [a.value for a in by_person[pid] if a.attribute == "alias"]
        if docs and not any(
            person_guard.in_text(person.display_name, texts[d], aliases) for d in docs
        ):
            name = None
            for d in docs:
                name = name or person_guard.supported_name(person.display_name, texts[d], aliases)
            if name is None:
                report.unresolved.append(pid)
            else:
                shown = "[masked]" if person.us_person else f"{person.display_name} -> {name}"
                report.names.append((pid, shown))
                person.display_name = name
        if person.name_key != (key := name_key(person.display_name)):
            person.name_key = key
            report.keys.append(pid)


def _fix_claims(
    session: Session, rows: list[PersonAttribute], texts: dict[int, str], report: Report
) -> None:
    seen = {(a.person_id, a.attribute, a.value, a.document_id, a.designation_id) for a in rows}
    for a in rows:
        if a.attribute == "alias" and a.document_id in texts:
            if not person_guard.in_text(a.value, texts[a.document_id]):
                report.aliases.append(a.person_id)
                session.delete(a)
        elif a.attribute == "title" and (value := person_guard.clean_title(a.value)) != a.value:
            report.titles.append(a.person_id)
            if value is None:
                session.delete(a)
                continue
            key_now = (a.person_id, a.attribute, value, a.document_id, a.designation_id)
            if key_now in seen:
                session.delete(a)
            else:
                seen.add(key_now)
                a.value = value


def _fix_quotes(session: Session, listed: dict[int | None, list[str]], report: Report) -> None:
    withheld: set[int] = set()
    for model in CLAIM_TABLES:
        claims: list[PersonAttribute | PersonOrganization | PersonEvent]
        claims = list(session.scalars(select(model)))
        for row in claims:
            if not row.evidence:
                continue
            if person_guard.safe_quote(row.evidence, listed[row.document_id]) is None:
                row.evidence = None
                withheld.add(row.person_id)
    report.quotes = sorted(withheld)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repair stored person records")
    parser.add_argument("--apply", action="store_true", help="write (default: report only)")
    args = parser.parse_args(argv)
    with session_factory()() as session:
        report = repair(session)
        if args.apply:
            session.commit()
        else:
            session.rollback()
    print("applied" if args.apply else "dry run: nothing written")
    for pid, change in report.names:
        print(f"  name #{pid}: {change}")
    for label in ("unresolved", "titles", "aliases", "quotes", "keys"):
        found = getattr(report, label)
        print(f"  {label}: {len(found)} {found}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

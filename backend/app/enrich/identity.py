"""Reviewed person identities (ADR 0013 amendment 1).

A merge is a link between records, made by the owner. Claims, citations and labels stay on
the record they were extracted to; views read linked records as one identity. Links form
trees: only the top record of an identity is ever linked, so there are no cycles and undoing
a link restores exactly the two identities it joined.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Person, PersonDistinction, PersonMerge


class MergeError(Exception):
    """A decision that conflicts with the records or with an earlier owner decision."""


@dataclass(frozen=True)
class Identities:
    """Every person record with the identity it currently belongs to."""

    people: dict[int, Person]
    root_of: dict[int, int]
    groups: dict[int, list[int]]
    distinct: frozenset[tuple[int, int]]  # pairs of identity roots

    def members(self, person_id: int) -> list[Person]:
        return [self.people[i] for i in self.groups[self.root_of[person_id]]]

    def us_person(self, person_id: int) -> bool:
        """Hidden by default if any linked record is flagged (hard rule 3)."""
        return any(p.us_person for p in self.members(person_id))

    def disputed(self, person_id: int) -> bool:
        return any(p.disputed for p in self.members(person_id))

    def marked_distinct(self, a: int, b: int) -> bool:
        x, y = sorted((self.root_of[a], self.root_of[b]))
        return (x, y) in self.distinct


def load(session: Session) -> Identities:
    people = {p.id: p for p in session.scalars(select(Person).order_by(Person.id))}
    parent: dict[int, int] = {
        m.member_id: m.into_id
        for m in session.scalars(select(PersonMerge).where(PersonMerge.undone_at.is_(None)))
    }
    root_of: dict[int, int] = {}
    groups: dict[int, list[int]] = defaultdict(list)
    for pid in people:
        top = pid
        while top in parent:
            top = parent[top]
        root_of[pid] = top
        groups[top].append(pid)
    pairs = set()
    for d in session.scalars(select(PersonDistinction)):
        if d.a_id in root_of and d.b_id in root_of:
            a, b = sorted((root_of[d.a_id], root_of[d.b_id]))
            pairs.add((a, b))
    return Identities(people, root_of, dict(groups), frozenset(pairs))


def _lock(session: Session) -> None:
    """Serialize owner decisions so two requests cannot build a cycle."""
    session.execute(select(Person.id).order_by(Person.id).with_for_update()).all()


def merge(
    session: Session, person_ids: Iterable[int], primary_id: int, note: str | None = None
) -> list[PersonMerge]:
    """Link each identity in ``person_ids`` to ``primary_id``, whose name is then displayed."""
    _lock(session)
    ids = load(session)
    chosen = set(person_ids) | {primary_id}
    if len(chosen) < 2:
        raise MergeError("choose at least two records")
    if any(ids.root_of.get(i) != i for i in chosen):
        raise MergeError("a record was deleted or already merged; refresh and review again")
    for a, b in combinations(sorted(chosen), 2):
        if ids.marked_distinct(a, b):
            raise MergeError(f"records {a} and {b} are marked as not the same person")
    made = [
        PersonMerge(member_id=i, into_id=primary_id, note=note)
        for i in sorted(chosen - {primary_id})
    ]
    session.add_all(made)
    session.flush()
    return made


def undo(session: Session, merge_id: int) -> PersonMerge | None:
    _lock(session)
    link = session.get(PersonMerge, merge_id)
    if link is None or link.undone_at is not None:
        return None
    link.undone_at = dt.datetime.now(dt.UTC)
    session.flush()
    return link


def mark_distinct(session: Session, person_id: int, other_ids: Sequence[int]) -> None:
    """Remember that ``person_id`` is none of ``other_ids``."""
    _lock(session)
    ids = load(session)
    if person_id not in ids.people or any(o not in ids.people for o in other_ids):
        raise MergeError("a record was deleted; refresh and review again")
    for other in other_ids:
        if ids.root_of[other] == ids.root_of[person_id]:
            raise MergeError("these records are merged; undo the merge first")
        a, b = sorted((person_id, other))
        session.execute(insert(PersonDistinction).values(a_id=a, b_id=b).on_conflict_do_nothing())
    session.flush()


def relink_before_delete(session: Session, doomed: set[int]) -> None:
    """Keep the rest of an identity linked when re-extraction removes some of its records."""
    if not doomed:
        return
    active = list(session.scalars(select(PersonMerge).where(PersonMerge.undone_at.is_(None))))
    if not any(m.member_id in doomed or m.into_id in doomed for m in active):
        return
    parent = {m.member_id: m.into_id for m in active}
    groups: dict[int, list[int]] = defaultdict(list)
    for node in sorted({*parent, *parent.values()}):
        top = node
        while top in parent:
            top = parent[top]
        groups[top].append(node)
    now = dt.datetime.now(dt.UTC)
    for top, nodes in groups.items():
        if not doomed & set(nodes):
            continue
        keep = [n for n in nodes if n not in doomed]
        head = top if top in keep else next(iter(keep), None)
        for m in active:
            if m.member_id in nodes:
                m.undone_at = now
        session.flush()
        session.add_all(
            PersonMerge(member_id=n, into_id=head, note="relinked after re-extraction")
            for n in keep
            if head is not None and n != head
        )
        session.flush()

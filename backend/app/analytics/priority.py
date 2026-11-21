"""Summaries for the priority topics (ADR 0009): unmanned systems and electricity theft.

The escalation ladder comes from the owner framework (docs/framework/
uxs-and-electricity-theft.md §1), which is owner judgment, not sourced fact. A rung is derived
from each event's reported platform, payload and mission. Only rungs the extraction fields can
show are derived:

- 1-2 observation or thermal reconnaissance: any reported use (a camera or thermal payload
  cannot be told apart from the text alone);
- 3 FPV or low-level flight: an FPV platform;
- 4 payload drops: a release mechanism, or explosives carried by a non-FPV platform;
- 5 one-way attacks: an FPV platform carrying explosives or an IED.

Rungs 6-8 (coordinated multi-drone operations, relays and repeaters, advanced autonomy) have no
extraction field yet, so they are listed as not captured rather than counted as zero.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.models import Event, Source

EXPLOSIVES = frozenset({"explosive_or_grenade", "ied"})
LADDER: tuple[tuple[int, str, bool], ...] = (
    (1, "Observation or thermal reconnaissance", True),
    (3, "FPV and low-level flight", True),
    (4, "Payload drops", True),
    (5, "One-way attacks", True),
    (6, "Coordinated multi-drone operations", False),
    (7, "Relays and repeaters", False),
    (8, "More advanced autonomy", False),
)
EMPLOYMENT = "employment"


def uxs_rung(platform: str | None, payloads: Iterable[str]) -> int:
    """Highest ladder rung an event's reported platform and payloads show (owner framework)."""
    loads = set(payloads)
    armed = bool(loads & EXPLOSIVES)
    if platform == "fpv" and armed:
        return 5
    if "release_mechanism" in loads or armed:
        return 4
    if platform == "fpv":
        return 3
    return 1


@dataclass
class LadderRow:
    rung: int
    label: str
    captured: bool
    use: int = 0  # reported employment
    capability: int = 0  # seizures, procurement, assembly, training, prosecutions
    first_seen: dt.date | None = None
    last_seen: dt.date | None = None

    def add(self, when: dt.date, *, use: bool) -> None:
        if use:
            self.use += 1
        else:
            self.capability += 1
        self.first_seen = min(self.first_seen, when) if self.first_seen else when
        self.last_seen = max(self.last_seen, when) if self.last_seen else when


@dataclass
class TopicSummary:
    total: int = 0
    sources: int = 0
    months: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    breakdown: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    states: Counter[str] = field(default_factory=Counter)
    ladder: list[LadderRow] = field(default_factory=list)


def _base(start: dt.date | None, end: dt.date | None, include_out_of_aoi: bool) -> Select[Event]:
    stmt = select(Event)
    if not include_out_of_aoi:
        stmt = stmt.where(Event.in_aoi.is_(True))
    if start:
        stmt = stmt.where(Event.event_date >= start)
    if end:
        stmt = stmt.where(Event.event_date <= end)
    return stmt


def _month(d: dt.date) -> str:
    return d.strftime("%Y-%m")


def _sources(session: Session, ids: list[int]) -> int:
    if not ids:
        return 0
    return (
        session.scalar(
            select(func.count(func.distinct(Source.id)))
            .join(Event, Event.source_id == Source.id)
            .where(Event.id.in_(ids))
        )
        or 0
    )


def uxs_summary(
    session: Session,
    start: dt.date | None = None,
    end: dt.date | None = None,
    include_out_of_aoi: bool = False,
) -> TopicSummary:
    stmt = _base(start, end, include_out_of_aoi).where(Event.uxs_activity.is_not(None))
    out = TopicSummary(ladder=[LadderRow(r, label, captured) for r, label, captured in LADDER])
    by_rung = {row.rung: row for row in out.ladder}
    ids: list[int] = []
    for ev in session.scalars(stmt):
        ids.append(ev.id)
        activity = ev.uxs_activity or "employment"
        out.months[_month(ev.event_date)][activity] += 1
        out.breakdown["activity"][activity] += 1
        out.breakdown["platform"][ev.uxs_platform or "unknown"] += 1
        for m in ev.uxs_missions or []:
            out.breakdown["mission"][m] += 1
        for p in ev.uxs_payloads or []:
            out.breakdown["payload"][p] += 1
        if ev.admin1_name:
            out.states[ev.admin1_name] += 1
        rung = uxs_rung(ev.uxs_platform, ev.uxs_payloads or [])
        by_rung[rung].add(ev.event_date, use=activity == EMPLOYMENT)
    out.total = len(ids)
    out.sources = _sources(session, ids)
    return out


def energy_summary(
    session: Session,
    start: dt.date | None = None,
    end: dt.date | None = None,
    include_out_of_aoi: bool = False,
) -> TopicSummary:
    stmt = _base(start, end, include_out_of_aoi).where(Event.energy_method.is_not(None))
    out = TopicSummary()
    ids: list[int] = []
    for ev in session.scalars(stmt):
        ids.append(ev.id)
        method = ev.energy_method or "unknown"
        out.months[_month(ev.event_date)][method] += 1
        out.breakdown["method"][method] += 1
        out.breakdown["facilitator"][ev.energy_facilitator or "none_reported"] += 1
        for p in ev.energy_powered or []:
            out.breakdown["powered"][p] += 1
        if ev.admin1_name:
            out.states[ev.admin1_name] += 1
    out.total = len(ids)
    out.sources = _sources(session, ids)
    return out

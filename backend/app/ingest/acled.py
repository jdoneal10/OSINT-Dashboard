"""ACLED ingester: violence events for the six Mexican border states (ADR 0003).

API (acleddata.com/api-documentation, read 2026-11-11):
- OAuth password grant at ``/oauth/token`` (``client_id=acled``); Bearer token, 24 h.
- ``/api/acled/read``: ``country``, ``event_date`` + ``event_date_where=BETWEEN``,
  ``timestamp`` + ``timestamp_where=>=`` for incremental pulls, cursor pagination
  (``next_cursor`` in JSON, ``X-Next-Cursor`` header), default 5,000 rows.
- ``/api/deleted/read``: ``event_id_cnty`` + ``deleted_timestamp``, updated weekly.
- ``event_id_cnty`` is stable across edits → upsert key.

Licence (personal, non-commercial; ADR 0003): internal use only, API access only, never sent
to any LLM, attributed with access date. Raw pages go to data/raw/acled/ (gitignored).

AOI filter: an event is kept when its ACLED admin1 name matches one of the six states
(accent/case-insensitive, allowing official long forms such as "Coahuila de Zaragoza"), or
its point falls inside a Phase 1 MEX reference polygon. Events that move out of the AOI on
revision are removed.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from geoalchemy2 import Geometry
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from shapely import wkt
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.prepared import PreparedGeometry, prep
from sqlalchemy import Boolean, cast, delete, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import ReturningInsert

from app.core.secrets import require_secret
from app.db.models import Event, IngestRun, ReferenceArea, Source
from app.db.session import session_factory
from app.enrich.actors import link_events
from app.ingest.http import PoliteClient
from app.ingest.raw import write_raw
from app.ingest.runs import RunContext, ingest_run, last_successful_params, source_id
from app.reference.normalize import normalize_alias

log = logging.getLogger(__name__)

SOURCE = "acled"
JOB_EVENTS = "acled-events"
JOB_DELETED = "acled-deleted"
BASE = "https://acleddata.com"
TOKEN_URL = f"{BASE}/oauth/token"
READ_URL = f"{BASE}/api/acled/read"
DELETED_URL = f"{BASE}/api/deleted/read"
COUNTRY = "Mexico"
PAGE_LIMIT = 5000

# Baseline record confidence from the source's Admiralty reliability grade (ADR 0003).
RELIABILITY_CONFIDENCE = {
    "A": Decimal("0.90"),
    "B": Decimal("0.75"),
    "C": Decimal("0.60"),
    "D": Decimal("0.40"),
    "E": Decimal("0.20"),
    "F": None,
}

ATTRIBUTE_FIELDS = (
    "actor1",
    "assoc_actor_1",
    "inter1",
    "actor2",
    "assoc_actor_2",
    "inter2",
    "interaction",
    "disorder_type",
    "civilian_targeting",
    "tags",
    "source",
    "source_scale",
    "admin3",
    "timestamp",
)


class AcledApiError(RuntimeError):
    """ACLED returned an error payload or an unexpected response."""


# --------------------------------------------------------------------------- records


class AcledEvent(BaseModel):
    """One ACLED event row. Unknown/extra fields are ignored."""

    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True)

    event_id_cnty: str
    event_date: dt.date
    time_precision: int | None = None
    disorder_type: str | None = None
    event_type: str
    sub_event_type: str | None = None
    actor1: str | None = None
    assoc_actor_1: str | None = None
    inter1: str | None = None
    actor2: str | None = None
    assoc_actor_2: str | None = None
    inter2: str | None = None
    interaction: str | None = None
    civilian_targeting: str | None = None
    country: str
    admin1: str | None = None
    admin2: str | None = None
    admin3: str | None = None
    location: str | None = None
    latitude: float
    longitude: float
    geo_precision: int | None = None
    source: str | None = None
    source_scale: str | None = None
    notes: str | None = None
    fatalities: int = 0
    tags: str | None = None
    timestamp: int

    @field_validator("*", mode="before")
    @classmethod
    def _blank_to_none(cls, v: Any) -> Any:
        return None if isinstance(v, str) and v.strip() == "" else v

    def attributes(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ATTRIBUTE_FIELDS if getattr(self, k) is not None}


# --------------------------------------------------------------------------- API client


class AcledClient:
    """OAuth + paginated reads. The token lives in memory only and is never logged."""

    def __init__(self, http: PoliteClient, username: str, password: str) -> None:
        self._http = http
        self._username = username
        self._password = password
        self._token: str | None = None

    def _authenticate(self) -> None:
        resp = self._http.post(
            TOKEN_URL,
            data={
                "username": self._username,
                "password": self._password,
                "grant_type": "password",
                "client_id": "acled",
                "scope": "authenticated",
            },
        )
        if resp.status_code != 200:
            raise AcledApiError(f"ACLED authentication failed (HTTP {resp.status_code})")
        token = resp.json().get("access_token")
        if not token:
            raise AcledApiError("ACLED authentication returned no access_token")
        self._token = str(token)

    def _get(self, url: str, params: dict[str, Any]) -> tuple[dict[str, Any], bytes, str | None]:
        if self._token is None:
            self._authenticate()
        for attempt in (1, 2):
            resp = self._http.get(
                url,
                params={"_format": "json", **params},
                headers={"Authorization": f"Bearer {self._token}"},
                crawl=False,  # documented API (EULA s.7.2), not a crawl
            )
            if resp.status_code == 401 and attempt == 1:
                log.info("ACLED token rejected; re-authenticating once")
                self._authenticate()
                continue
            break
        if resp.status_code != 200:
            raise AcledApiError(f"GET {url} failed with HTTP {resp.status_code}")
        body = resp.json()
        if body.get("success") is False or body.get("status") not in (None, 200, "200"):
            raise AcledApiError(f"ACLED error: {body.get('messages') or body.get('error')}")
        cursor = body.get("next_cursor", resp.headers.get("X-Next-Cursor"))
        return body, resp.content, (str(cursor) if cursor not in (None, "", "null") else None)

    def pages(
        self, url: str, params: dict[str, Any]
    ) -> Iterator[tuple[list[dict[str, Any]], bytes]]:
        cursor: str | None = "0"
        while cursor is not None:
            body, raw, cursor = self._get(url, {**params, "limit": PAGE_LIMIT, "cursor": cursor})
            data = body.get("data") or []
            yield data, raw
            if not data:
                break


def _client(http: PoliteClient) -> AcledClient:
    return AcledClient(
        http,
        require_secret("ACLED_USERNAME").get_secret_value(),
        require_secret("ACLED_PASSWORD").get_secret_value(),
    )


# --------------------------------------------------------------------------- AOI


@dataclass
class Aoi:
    names: dict[str, str]  # normalized state name → admin1 code
    shapes: list[tuple[str, PreparedGeometry]]

    def admin1_code(self, ev: AcledEvent) -> str | None:
        if ev.admin1:
            name = normalize_alias(ev.admin1)
            for ref, code in self.names.items():
                if name == ref or name.startswith(ref + " de "):
                    return code
        point = Point(ev.longitude, ev.latitude)
        for code, geom in self.shapes:
            if geom.contains(point):
                return code
        return None


def load_aoi(session: Session) -> Aoi:
    rows = session.execute(
        select(
            ReferenceArea.name,
            ReferenceArea.admin1_code,
            func.ST_AsText(cast(ReferenceArea.geom, Geometry)),
        ).where(ReferenceArea.country_iso3 == "MEX", ReferenceArea.phase == 1)
    ).all()
    if not rows:
        raise RuntimeError("no Phase 1 MEX reference areas loaded; run `make seed` first")
    names = {normalize_alias(name): code for name, code, _ in rows if code}
    shapes: list[tuple[str, PreparedGeometry]] = []
    for _, code, text in rows:
        geom: BaseGeometry = wkt.loads(text)
        shapes.append((code, prep(geom)))
    return Aoi(names=names, shapes=shapes)


# --------------------------------------------------------------------------- loading


def _confidence(session: Session) -> Decimal | None:
    grade = session.scalar(select(Source.reliability).where(Source.slug == SOURCE))
    return RELIABILITY_CONFIDENCE.get(grade or "F")


def upsert_page(session: Session, records: list[dict[str, Any]], aoi: Aoi) -> dict[str, int]:
    """Validate, AOI-filter and upsert one page. Returns counters."""
    stats = {"inserted": 0, "updated": 0, "outside": 0, "invalid": 0, "removed": 0}
    sid = source_id(session, SOURCE)
    confidence = _confidence(session)
    now = dt.datetime.now(dt.UTC)
    values: list[dict[str, Any]] = []
    outside: list[str] = []
    for raw in records:
        try:
            ev = AcledEvent.model_validate(raw)
        except ValidationError as exc:
            stats["invalid"] += 1
            log.warning("invalid ACLED record %s: %s", raw.get("event_id_cnty"), exc.errors()[:2])
            continue
        code = aoi.admin1_code(ev)
        if code is None:
            stats["outside"] += 1
            outside.append(ev.event_id_cnty)
            continue
        values.append(
            {
                "source_id": sid,
                "source_key": ev.event_id_cnty,
                "source_url": "https://acleddata.com",
                "retrieved_at": now,
                "confidence": confidence,
                "event_date": ev.event_date,
                "event_type": ev.event_type,
                "sub_event_type": ev.sub_event_type,
                "description": ev.notes,
                "fatalities": ev.fatalities,
                "geom": func.ST_GeogFromText(f"SRID=4326;POINT({ev.longitude} {ev.latitude})"),
                "country_iso3": "MEX",
                "admin1_code": code,
                "admin1_name": ev.admin1,
                "admin2_name": ev.admin2,
                "location_name": ev.location,
                "geo_precision": ev.geo_precision,
                "time_precision": ev.time_precision,
                "attributes": ev.attributes(),
            }
        )
    if outside:  # revised out of the AOI → remove any copy we hold
        removed = session.scalars(
            delete(Event)
            .where(Event.source_id == sid, Event.source_key.in_(outside))
            .returning(Event.id)
        ).all()
        stats["removed"] = len(removed)
    event_ids: list[int] = []
    if values:
        base = insert(Event).values(values)
        update_cols = {
            k: base.excluded[k] for k in values[0] if k not in ("source_id", "source_key")
        }
        stmt: ReturningInsert[int, bool] = base.on_conflict_do_update(
            constraint="uq_events_source_key",
            set_=update_cols | {"updated_at": func.now()},
        ).returning(Event.id, literal_column("(xmax = 0)", Boolean))
        for event_id, was_insert in session.execute(stmt):
            event_ids.append(event_id)
            stats["inserted" if was_insert else "updated"] += 1
        link_events(session, event_ids)
    return stats


# --------------------------------------------------------------------------- jobs


def _accumulate(run: RunContext, stats: dict[str, int]) -> None:
    run.inserted += stats["inserted"]
    run.updated += stats["updated"]
    run.deleted += stats["removed"]
    for key in ("outside", "invalid"):
        run.params[key] = run.params.get(key, 0) + stats[key]


def run_events(
    since: dt.date | None = None,
    *,
    until: dt.date | None = None,
    http: PoliteClient | None = None,
) -> int:
    """Backfill from ``since`` or, without it, pull records updated since the last watermark."""
    started = int(dt.datetime.now(dt.UTC).timestamp())
    params: dict[str, Any] = {"country": COUNTRY}
    if since is not None:
        end = until or dt.datetime.now(dt.UTC).date()
        params |= {"event_date": f"{since}|{end}", "event_date_where": "BETWEEN"}
        mode = "backfill"
    else:
        last = last_successful_params(JOB_EVENTS)
        if not last or "max_timestamp" not in last:
            raise RuntimeError("no previous ACLED run; backfill first with SINCE=2018-01-01")
        params |= {"timestamp": int(last["max_timestamp"]), "timestamp_where": ">="}
        mode = "incremental"

    owns = http is None
    http = http or PoliteClient()
    try:
        client = _client(http)
        run_params = {"mode": mode, "query": params, "started_unix": started}
        with ingest_run(JOB_EVENTS, source_slug=SOURCE, params=run_params) as run:
            with session_factory()() as session:
                aoi = load_aoi(session)
            max_ts = int(params.get("timestamp", 0))
            for n, (records, raw) in enumerate(client.pages(READ_URL, params), start=1):
                snap = write_raw(SOURCE, run.id, f"events-page-{n:04d}.json", raw)
                run.raw_paths.append(str(snap.path))
                with session_factory()() as session, session.begin():
                    _accumulate(run, upsert_page(session, records, aoi))
                for rec in records:
                    ts = rec.get("timestamp")
                    if ts is not None and str(ts).isdigit():
                        max_ts = max(max_ts, int(ts))
                run.params["pages"] = n
            run.params["max_timestamp"] = max_ts or started
    finally:
        if owns:
            http.close()
    return 0


def _deleted_watermark() -> int:
    last = last_successful_params(JOB_DELETED)
    if last and "max_deleted_timestamp" in last:
        return int(last["max_deleted_timestamp"])
    # Deletions before our first backfill never reached us.
    with session_factory()() as session:
        first = session.scalar(
            select(IngestRun.params)
            .where(IngestRun.job == JOB_EVENTS, IngestRun.status == "ok")
            .order_by(IngestRun.started_at.asc())
            .limit(1)
        )
    if not first:
        raise RuntimeError("no ACLED events run yet; nothing to reconcile")
    return int(first.get("started_unix", 0))


def run_deleted(*, http: PoliteClient | None = None) -> int:
    """Hard-delete events ACLED has removed (cascades to actor_events)."""
    watermark = _deleted_watermark()
    params = {"deleted_timestamp": watermark, "deleted_timestamp_where": ">="}
    owns = http is None
    http = http or PoliteClient()
    try:
        client = _client(http)
        with ingest_run(JOB_DELETED, source_slug=SOURCE, params={"query": params}) as run:
            max_ts = watermark
            for n, (records, raw) in enumerate(client.pages(DELETED_URL, params), start=1):
                snap = write_raw(SOURCE, run.id, f"deleted-page-{n:04d}.json", raw)
                run.raw_paths.append(str(snap.path))
                ids = [str(r["event_id_cnty"]) for r in records if r.get("event_id_cnty")]
                with session_factory()() as session, session.begin():
                    sid = source_id(session, SOURCE)
                    if ids:
                        removed = session.scalars(
                            delete(Event)
                            .where(Event.source_id == sid, Event.source_key.in_(ids))
                            .returning(Event.id)
                        ).all()
                        run.deleted += len(removed)
                for r in records:
                    ts = r.get("deleted_timestamp")
                    if ts is not None and str(ts).isdigit():
                        max_ts = max(max_ts, int(ts))
            run.params["max_deleted_timestamp"] = max_ts
    finally:
        if owns:
            http.close()
    return 0

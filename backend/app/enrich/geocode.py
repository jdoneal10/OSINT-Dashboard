"""Geocoding against the local INEGI gazetteer (``places``) — no external service (ADR 0004).

Resolution order for a place mention (locality / municipality / state, as extracted):

1. State -> ISO 3166-2 code, matching INEGI or Natural Earth names in short or official
   long form ("Coahuila" == "Coahuila de Zaragoza").
2. Municipality within that state (or nationally, if unique).
3. Locality within that municipality, else within the state; ties -> most populous.

Precision: 1 locality, 2 municipality, 3 state (label point). A municipality's point is its
seat (cabecera, INEGI locality 0001, e.g. Culiacán Rosales), not the polygon centre, which
in large municipalities can be tens of kilometres from the city. A place mention equal to
the municipality's name ("Culiacán") resolves to the seat at locality precision.
U.S. mentions resolve only within the four border states in ``reference_areas``: a place or
city naming a cited port of entry (``nodes``, node_type ``poe``) takes that node's point at
precision 2 and its ``node_id``; otherwise the state label point at precision 3. Other
countries and U.S. states are outside the AOI and stay unresolved.
Unresolved -> ``None`` (the event keeps its text but has no point).
"""

from __future__ import annotations

from dataclasses import dataclass

from geoalchemy2 import Geometry
from sqlalchemy import Select, cast, func, select
from sqlalchemy.orm import Session

from app.db.models import Node, Place, ReferenceArea
from app.reference.inegi_load import place_key

MEXICO = {"mexico", "méxico", "mx", "mex"}
# Phase 2 AOI: all of Mexico plus the four U.S. border states. Phase 4 adds Central America.
US_BORDER_STATES = {"arizona", "california", "new mexico", "texas", "az", "ca", "nm", "tx"}
USA = {"united states", "united states of america", "usa", "us", "u s", "u s a",
       "estados unidos", "eeuu", "ee uu"}  # fmt: skip


@dataclass(frozen=True)
class GeoResult:
    lon: float
    lat: float
    admin1_code: str
    admin2_code: str | None
    precision: int  # 1 locality, 2 municipality / port of entry, 3 state
    matched: str
    country_iso3: str = "MEX"
    node_id: int | None = None

    @property
    def ewkt(self) -> str:
        return f"SRID=4326;POINT({self.lon} {self.lat})"


def _xy(session: Session, place: Place) -> tuple[float, float] | None:
    if place.point is None:
        return None
    x, y = session.execute(
        select(
            func.ST_X(cast(Place.point, Geometry)), func.ST_Y(cast(Place.point, Geometry))
        ).where(Place.id == place.id)
    ).one()
    return float(x), float(y)


def resolve_state(session: Session, name: str | None) -> tuple[str, str] | None:
    """(admin1_code, canonical name) for a Mexican state mention."""
    if not name:
        return None
    key = place_key(name)
    if not key:
        return None
    candidates: list[tuple[str, str]] = [
        (p.name_normalized, p.admin1_code)
        for p in session.scalars(select(Place).where(Place.place_type == "state"))
    ]
    candidates += [
        (place_key(n), c)
        for n, c in session.execute(
            select(ReferenceArea.name, ReferenceArea.admin1_code).where(
                ReferenceArea.country_iso3 == "MEX", ReferenceArea.area_type == "admin1"
            )
        )
        if c
    ]
    for cand_key, code in candidates:
        if (
            key == cand_key
            or cand_key.startswith(key + " de ")
            or key.startswith(cand_key + " de ")
        ):
            return code, name
    if key in {"cdmx", "df", "distrito federal"}:
        return "MX-CMX", name
    return None


def _state_point(session: Session, code: str) -> tuple[float, float] | None:
    row = session.execute(
        select(
            func.ST_X(func.ST_PointOnSurface(cast(ReferenceArea.geom, Geometry))),
            func.ST_Y(func.ST_PointOnSurface(cast(ReferenceArea.geom, Geometry))),
        )
        .where(ReferenceArea.admin1_code == code, ReferenceArea.area_type == "admin1")
        .limit(1)
    ).first()
    return (float(row[0]), float(row[1])) if row else None


def _seat(session: Session, mun: Place) -> tuple[float, float] | None:
    """Coordinates of the municipal seat (INEGI locality code <cvegeo>0001)."""
    seat = session.scalars(
        select(Place).where(Place.source == mun.source, Place.code == f"{mun.code}0001")
    ).first()
    return _xy(session, seat) if seat is not None else None


def _best(session: Session, query: Select[Place]) -> Place | None:
    rows: list[Place] = list(session.scalars(query))
    if not rows:
        return None
    return max(rows, key=lambda p: (p.point is not None, p.population or 0))


def _find_municipality(session: Session, name: str | None, admin1: str | None) -> Place | None:
    """A municipality by name, inside the state if known, else only if nationally unique."""
    if not name:
        return None
    q = select(Place).where(
        Place.place_type == "municipality", Place.name_normalized == place_key(name)
    )
    if admin1:
        q = q.where(Place.admin1_code == admin1)
    matches = list(session.scalars(q))
    if len(matches) == 1 or (matches and admin1):
        return max(matches, key=lambda p: p.population or 0)
    return None


def _find_locality(
    session: Session, name: str | None, mun: Place | None, admin1: str | None
) -> GeoResult | None:
    if not name or (mun is None and not admin1):
        return None  # a bare locality name with no state is too ambiguous
    q = select(Place).where(
        Place.place_type == "locality", Place.name_normalized == place_key(name)
    )
    q = q.where(Place.admin2_code == mun.code) if mun else q.where(Place.admin1_code == admin1)
    loc = _best(session, q)
    xy = _xy(session, loc) if loc is not None else None
    if loc is None or xy is None:
        return None
    return GeoResult(xy[0], xy[1], loc.admin1_code, loc.admin2_code, 1, loc.name)


def _municipality_result(mun: Place, xy: tuple[float, float], place: str | None) -> GeoResult:
    # A place equal to the municipality's name ("Culiacán") is its seat -> locality precision.
    same = place is not None and place_key(place) == mun.name_normalized
    return GeoResult(xy[0], xy[1], mun.admin1_code, mun.code, 1 if same else 2, mun.name)


def geocode(
    session: Session,
    *,
    place: str | None,
    municipality: str | None,
    state: str | None,
    country: str | None = "Mexico",
) -> GeoResult | None:
    if country and place_key(country) in USA:
        return _geocode_us(session, place=place, municipality=municipality, state=state)
    if country and place_key(country) not in MEXICO:
        return None  # outside the AOI gazetteers
    st = resolve_state(session, state)
    admin1 = st[0] if st else None
    mun = _find_municipality(session, municipality, admin1)

    hit = _find_locality(session, place, mun, admin1)
    if hit is None and mun is None:
        hit = _find_locality(session, municipality, None, admin1)
    if hit is not None:
        return hit

    if mun is None and admin1:
        # "Culiacán, Sinaloa": the place names the municipality (seat named differently).
        mun = _find_municipality(session, place, admin1)
    if mun is not None and (xy := _seat(session, mun) or _xy(session, mun)):
        return _municipality_result(mun, xy, place)
    if admin1 and (xy := _state_point(session, admin1)):
        return GeoResult(xy[0], xy[1], admin1, None, 3, st[1] if st else admin1)
    return None


def _geocode_us(
    session: Session, *, place: str | None, municipality: str | None, state: str | None
) -> GeoResult | None:
    key = place_key(state or "")
    if not key:
        return None
    area = next(
        (
            (name, code)
            for name, code in session.execute(
                select(ReferenceArea.name, ReferenceArea.admin1_code).where(
                    ReferenceArea.country_iso3 == "USA", ReferenceArea.area_type == "admin1"
                )
            )
            if code and (place_key(name) == key or code.removeprefix("US-").lower() == key)
        ),
        None,
    )
    if area is None:
        return None  # not a border state: outside the AOI
    name, code = area
    mentions = [place_key(m) for m in (municipality, place) if m]
    ports = session.execute(
        select(
            Node.id,
            Node.name,
            func.ST_X(cast(Node.point, Geometry)),
            func.ST_Y(cast(Node.point, Geometry)),
        ).where(Node.node_type == "poe", Node.admin1_code == code, Node.point.is_not(None))
    ).all()
    # Longest name first so "Calexico East" wins over "Calexico".
    for node_id, node_name, x, y in sorted(ports, key=lambda r: -len(r[1])):
        nk = place_key(node_name)
        if any(m == nk or f" {nk} " in f" {m} " for m in mentions):
            return GeoResult(float(x), float(y), code, None, 2, node_name, "USA", node_id)
    if xy := _state_point(session, code):
        return GeoResult(xy[0], xy[1], code, None, 3, name, "USA")
    return None


def in_aoi(country: str | None, state: str | None) -> bool:
    """Whether an extracted location falls in the current AOI.

    Unknown country or U.S. state counts as inside (hide only what is clearly elsewhere):
    a national DOJ indictment with no state stays visible; one in South Carolina does not.
    """
    if not country:
        return True
    key = place_key(country)
    if key in MEXICO:
        return True
    if key in USA:
        return not state or place_key(state) in US_BORDER_STATES
    return False

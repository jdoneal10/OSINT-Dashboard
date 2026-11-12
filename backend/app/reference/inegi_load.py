"""Load downloaded INEGI files into PostGIS (idempotent upserts).

- ``reference_areas``: one row per municipality (``area_type='admin2'``, phase 2), geometry
  simplified to ~50 m, with ``admin1_code`` (ISO 3166-2) and ``admin2_code`` (INEGI cvegeo).
- ``places``: the geocoding gazetteer: states, municipalities (representative point of the
  polygon) and localities (INEGI coordinates). Bracketed type suffixes such as "[Rancho]" are
  kept in ``name`` but dropped from ``name_normalized`` so "Valentina" matches.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Place, ReferenceArea
from app.db.session import session_factory
from app.reference.inegi import CITATION, CVE_ENT_ISO, raw_dir
from app.reference.normalize import normalize_alias

log = logging.getLogger(__name__)

SIMPLIFY_DEG = 0.0005  # ~50 m: fine for municipal choropleths and point-in-polygon
BATCH = 5000
_BRACKETS = re.compile(r"\[[^\]]*\]|\([^)]*\)")


def place_key(name: str) -> str:
    """Normalized gazetteer key: accents/case/punctuation folded, bracketed suffixes dropped."""
    return normalize_alias(_BRACKETS.sub(" ", name))


def _int(value: Any) -> int | None:
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _citation() -> list[dict[str, Any]]:
    return [CITATION | {"accessed": dt.date.today().isoformat()}]  # noqa: DTZ011


def _ewkt(geom: BaseGeometry) -> Any:
    return func.ST_GeogFromText(f"SRID=4326;{geom.wkt}")


def _multipolygon(geom: BaseGeometry) -> MultiPolygon | None:
    geom = geom.simplify(SIMPLIFY_DEG, preserve_topology=True).buffer(0)
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    if isinstance(geom, MultiPolygon):
        return geom
    parts = [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]
    return MultiPolygon(parts) if parts else None


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _upsert(session: Session, model: Any, rows: list[dict[str, Any]], keys: list[str]) -> None:
    for start in range(0, len(rows), BATCH):
        chunk = rows[start : start + BATCH]
        base = insert(model).values(chunk)
        session.execute(
            base.on_conflict_do_update(
                index_elements=keys,
                set_={k: base.excluded[k] for k in chunk[0] if k not in keys},
            )
        )


def _municipality_rows(ent: str, root: Path) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """Yield (reference_area row, place row) per municipality of state ``ent``."""
    iso = CVE_ENT_ISO[ent]
    catalog = {m["cvegeo"]: m for m in _read(root / f"mgem_{ent}.json")["datos"]}
    citation = _citation()
    for feature in _read(root / f"geo_mgem_{ent}.json")["features"]:
        props = feature["properties"]
        code = props["cvegeo"]
        geom = _multipolygon(shape(feature["geometry"]))
        if geom is None or geom.is_empty:
            log.warning("municipality %s has no usable geometry; skipped", code)
            continue
        name = props["nomgeo"]
        area = {
            "slug": f"mx-mun-{code}",
            "name": name,
            "area_type": "admin2",
            "country_iso3": "MEX",
            "admin1_code": iso,
            "admin2_code": code,
            "phase": 2,
            "geom": _ewkt(geom),
            "sources": citation,
        }
        place = {
            "source": "inegi",
            "code": code,
            "place_type": "municipality",
            "name": name,
            "name_normalized": place_key(name),
            "country_iso3": "MEX",
            "admin1_code": iso,
            "admin2_code": code,
            "point": _ewkt(geom.representative_point()),
            "population": _int(catalog.get(code, {}).get("pob_total")),
            "urban": None,
        }
        yield area, place


def _locality_rows(root: Path) -> Iterator[dict[str, Any]]:
    for path in sorted((root / "localidades").glob("*.json")):
        for loc in _read(path).get("datos", []):
            lat, lon = _float(loc.get("latitud")), _float(loc.get("longitud"))
            ent = loc["cve_ent"]
            yield {
                "source": "inegi",
                "code": loc["cvegeo"],
                "place_type": "locality",
                "name": loc["nomgeo"],
                "name_normalized": place_key(loc["nomgeo"]),
                "country_iso3": "MEX",
                "admin1_code": CVE_ENT_ISO[ent],
                "admin2_code": f"{ent}{loc['cve_mun']}",
                "point": func.ST_GeogFromText(f"SRID=4326;POINT({lon} {lat})")
                if lat is not None and lon is not None
                else None,
                "population": _int(loc.get("pob_total")),
                "urban": (loc.get("ambito") or "").upper() == "URBANO",
            }


def load() -> dict[str, int]:
    root = raw_dir()
    states = _read(root / "mgee.json")["datos"]
    counts = {"municipalities": 0, "localities": 0, "states": 0}
    with session_factory()() as session, session.begin():
        _upsert(
            session,
            Place,
            [
                {
                    "source": "inegi",
                    "code": s["cvegeo"],
                    "place_type": "state",
                    "name": s["nomgeo"],
                    "name_normalized": place_key(s["nomgeo"]),
                    "country_iso3": "MEX",
                    "admin1_code": CVE_ENT_ISO[s["cve_ent"]],
                    "admin2_code": None,
                    "point": None,
                    "population": _int(s.get("pob_total")),
                    "urban": None,
                }
                for s in states
            ],
            ["source", "code"],
        )
        counts["states"] = len(states)
        for state in states:
            ent = state["cve_ent"]
            if not (root / f"geo_mgem_{ent}.json").is_file():
                log.warning("state %s not downloaded yet; skipped", ent)
                continue
            pairs = list(_municipality_rows(ent, root))
            # Geometry rows are large; insert per state and in small chunks.
            for start in range(0, len(pairs), 100):
                chunk = pairs[start : start + 100]
                _upsert(session, ReferenceArea, [a for a, _ in chunk], ["slug"])
                _upsert(session, Place, [p for _, p in chunk], ["source", "code"])
            counts["municipalities"] += len(pairs)
        batch: list[dict[str, Any]] = []
        for row in _locality_rows(root):
            batch.append(row)
            if len(batch) >= BATCH:
                _upsert(session, Place, batch, ["source", "code"])
                counts["localities"] += len(batch)
                batch = []
        if batch:
            _upsert(session, Place, batch, ["source", "code"])
            counts["localities"] += len(batch)
    log.info("INEGI loaded: %s", counts)
    return counts

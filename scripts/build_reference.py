"""Rebuild committed reference GeoJSON from public-domain source snapshots.

Inputs (downloaded into data/raw/reference/<date>/, which is gitignored):
  - ne_10m_admin_1_states_provinces.zip  Natural Earth 10m admin-1 (public domain)
      https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_1_states_provinces.zip
  - bts_us_mexico_ports.json             BTS Border Crossing Entry Data (keg4-3bc2),
      distinct US-Mexico ports with published coordinates

Outputs (committed):
  - data/reference/aoi_phase1.geojson    6 Mexican + 4 U.S. border states, simplified
  - data/reference/nodes.geojson         SW land POEs (points) + 9 USBP sectors (no geometry)

USBP sectors carry no geometry: no current public boundary dataset exists (ADR 0002).

Run from the repo root:
  uv run --project backend --with pyshp python scripts/build_reference.py data/raw/reference/2026-11-11
"""

from __future__ import annotations

import io
import json
import re
import sys
import unicodedata
import zipfile
from pathlib import Path
from typing import Any

import shapefile  # pyshp
from shapely.geometry import MultiPolygon, Polygon, mapping, shape

ACCESSED = "2026-11-11"
SIMPLIFY_DEG = 0.005  # ~500 m; reference-scale outlines, keeps the file small
PRECISION = 4

NE_CITATION = {
    "title": "Admin 1 – States, Provinces (1:10m, v5.1)",
    "publisher": "Natural Earth (public domain)",
    "url": "https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-1-states-provinces/",
    "accessed": ACCESSED,
}
BTS_CITATION = {
    "title": "Border Crossing Entry Data (dataset keg4-3bc2)",
    "publisher": "U.S. DOT Bureau of Transportation Statistics, from CBP data",
    "url": "https://data.bts.gov/Research-and-Statistics/Border-Crossing-Entry-Data/keg4-3bc2",
    "accessed": ACCESSED,
    "note": "Port coordinates as published by BTS; one point per BTS port code.",
}
CBP_SECTORS_INDEX = "https://www.cbp.gov/border-security/along-us-borders/border-patrol-sectors"

# Phase 1 AOI: ISO 3166-2 codes as used by Natural Earth.
AOI_STATES = {
    "MX-BCN": "baja-california",
    "MX-SON": "sonora",
    "MX-CHH": "chihuahua",
    "MX-COA": "coahuila",
    "MX-NLE": "nuevo-leon",
    "MX-TAM": "tamaulipas",
    "US-CA": "california",
    "US-AZ": "arizona",
    "US-NM": "new-mexico",
    "US-TX": "texas",
}

# The nine Southwest Border USBP sectors, named as on CBP's public sector index.
SECTORS = [
    ("san-diego", "San Diego Sector", "California", "san-diego-sector-california"),
    ("el-centro", "El Centro Sector", "California", "el-centro-sector-california"),
    ("yuma", "Yuma Sector", "Arizona", "yuma-sector-arizona"),
    ("tucson", "Tucson Sector", "Arizona", "tucson-sector-arizona"),
    ("el-paso", "El Paso Sector", "Texas", "el-paso-sector-texas"),
    ("big-bend", "Big Bend Sector", "Texas", "big-bend-sector-texas"),
    ("del-rio", "Del Rio Sector", "Texas", "del-rio-sector-texas"),
    ("laredo", "Laredo Sector", "Texas", "laredo-sector-texas"),
    ("rio-grande-valley", "Rio Grande Valley Sector", "Texas", "rio-grande-valley-sector-texas"),
]

# The four Southwest OFO field offices, labeled exactly as in CBP's public statistics (the
# "Area of Responsibility" column). Statistical units only; no facility locations.
CBP_ENCOUNTERS_PAGE = "https://www.cbp.gov/document/stats/nationwide-encounters"
FIELD_OFFICES = [
    ("san-diego", "San Diego Field Office", "California"),
    ("tucson", "Tucson Field Office", "Arizona"),
    ("el-paso", "El Paso Field Office", "Texas"),
    ("laredo", "Laredo Field Office", "Texas"),
]

US_STATE_CODES = {"California": "US-CA", "Arizona": "US-AZ", "New Mexico": "US-NM", "Texas": "US-TX"}


def _round(obj: Any) -> Any:
    if isinstance(obj, float):
        return round(obj, PRECISION)
    if isinstance(obj, (list, tuple)):
        return [_round(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    return obj


def _slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


# Natural Earth still carries Mexico City's pre-2016 code/name; map to current ISO 3166-2.
NE_RENAMES = {"MX-DIF": ("MX-CMX", "Ciudad de México")}


def build_aoi(ne_zip: Path, phase: int = 1) -> dict[str, Any]:
    """Phase 1: the ten border states. Phase 2: every other Mexican state."""
    with zipfile.ZipFile(ne_zip) as zf:
        names = {Path(n).suffix: n for n in zf.namelist() if Path(n).stem.endswith("provinces")}
        reader = shapefile.Reader(
            shp=io.BytesIO(zf.read(names[".shp"])),
            shx=io.BytesIO(zf.read(names[".shx"])),
            dbf=io.BytesIO(zf.read(names[".dbf"])),
            encoding="utf-8",
        )
        features = []
        for rec in reader.iterShapeRecords():
            code, name = rec.record["iso_3166_2"], rec.record["name"]
            code, name = NE_RENAMES.get(code, (code, name))
            if phase == 1:
                if code not in AOI_STATES:
                    continue
                slug = f"{code.split('-')[0].lower()}-{AOI_STATES[code]}"
            else:
                if rec.record["adm0_a3"] != "MEX" or code in AOI_STATES or not name:
                    continue  # skips the unnamed Natural Earth island polygon (MX-X01~)
                slug = f"mx-{_slugify(name)}"
            geom = shape(rec.shape.__geo_interface__)
            geom = geom.simplify(SIMPLIFY_DEG, preserve_topology=True).buffer(0)
            if isinstance(geom, Polygon):
                geom = MultiPolygon([geom])
            country = "MEX" if code.startswith("MX") else "USA"
            features.append(
                {
                    "type": "Feature",
                    "geometry": _round(mapping(geom)),
                    "properties": {
                        "slug": slug,
                        "name": name,
                        "area_type": "admin1",
                        "country_iso3": country,
                        "admin1_code": code,
                        "phase": phase,
                        "sources": [NE_CITATION],
                    },
                }
            )
    missing = set(AOI_STATES) - {f["properties"]["admin1_code"] for f in features}
    if phase == 1 and missing:
        raise SystemExit(f"Natural Earth is missing AOI states: {sorted(missing)}")
    features.sort(key=lambda f: (f["properties"]["country_iso3"], f["properties"]["name"]))
    return {"type": "FeatureCollection", "features": features}


def build_nodes(bts_json: Path) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for row in sorted(json.loads(bts_json.read_text()), key=lambda r: r["port_code"]):
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        round(float(row["longitude"]), 5),
                        round(float(row["latitude"]), 5),
                    ],
                },
                "properties": {
                    "slug": f"poe-{row['port_code']}-{_slugify(row['port_name'])}",
                    "name": row["port_name"],
                    "node_type": "poe",
                    "code": row["port_code"],
                    "country_iso3": "USA",
                    "admin1_code": US_STATE_CODES[row["state"]],
                    "attributes": {"border": "US-Mexico", "state": row["state"]},
                    "sources": [BTS_CITATION],
                },
            }
        )
    for slug, name, state, page in SECTORS:
        features.append(
            {
                "type": "Feature",
                "geometry": None,
                "properties": {
                    "slug": f"usbp-{slug}",
                    "name": name,
                    "node_type": "usbp_sector",
                    "country_iso3": "USA",
                    "admin1_code": US_STATE_CODES[state],
                    "attributes": {
                        "state": state,
                        "geometry_status": "none: no current public boundary dataset (ADR 0002)",
                    },
                    "sources": [
                        {
                            "title": f"{name}, {state}",
                            "publisher": "U.S. Customs and Border Protection",
                            "url": f"{CBP_SECTORS_INDEX}/{page}",
                            "accessed": ACCESSED,
                        }
                    ],
                },
            }
        )
    for slug, name, state in FIELD_OFFICES:
        features.append(
            {
                "type": "Feature",
                "geometry": None,
                "properties": {
                    "slug": f"ofo-{slug}",
                    "name": name,
                    "node_type": "ofo_field_office",
                    "country_iso3": "USA",
                    "admin1_code": US_STATE_CODES[state],
                    "attributes": {
                        "state": state,
                        "aor_label": name,
                        "geometry_status": "none: statistical area of responsibility (ADR 0002)",
                    },
                    "sources": [
                        {
                            "title": "Nationwide Encounters (Area of Responsibility files)",
                            "publisher": "U.S. Customs and Border Protection",
                            "url": CBP_ENCOUNTERS_PAGE,
                            "accessed": ACCESSED,
                            "note": f"AOR label '{name}' as published in the AOR column.",
                        }
                    ],
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _write(path: Path, data: dict[str, Any]) -> None:
    lines = ",\n".join(json.dumps(f, ensure_ascii=False) for f in data["features"])
    path.write_text(
        '{"type": "FeatureCollection", "features": [\n' + lines + "\n]}\n", encoding="utf-8"
    )
    print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KB, {len(data['features'])} features)")


def main(raw_dir: str) -> None:
    raw = Path(raw_dir)
    out = Path("data/reference")
    out.mkdir(parents=True, exist_ok=True)
    ne = raw / "ne_10m_admin_1_states_provinces.zip"
    _write(out / "aoi_phase1.geojson", build_aoi(ne, phase=1))
    phase2 = build_aoi(ne, phase=2)
    if len(phase2["features"]) != 26:
        raise SystemExit(f"expected 26 non-border Mexican states, got {len(phase2['features'])}")
    _write(out / "aoi_phase2.geojson", phase2)
    _write(out / "nodes.geojson", build_nodes(raw / "bts_us_mexico_ports.json"))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])

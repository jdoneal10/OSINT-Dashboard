"""INEGI geostatistical reference data: municipalities (admin2) and the localities gazetteer.

Source: INEGI Catálogo Único de Claves Geoestadísticas web service
(https://gaia.inegi.org.mx/wscatgeo/v2), under INEGI's free-use terms
(https://www.inegi.org.mx/inegi/terminos.html): reuse and transformation allowed with the
attribution "Fuente: INEGI, <product>"; transformations must be disclosed and never presented
as INEGI's own. Large raw files stay in data/raw/reference/inegi/ (gitignored); only code is
committed. ADR 0004.

    uv run python -m app.reference.inegi download   # resumable; ~2,500 requests at 1/s
    uv run python -m app.reference.inegi load       # simplify and upsert into PostGIS
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.ingest.http import PoliteClient

log = logging.getLogger(__name__)

BASE = "https://gaia.inegi.org.mx/wscatgeo/v2"
CITATION = {
    "title": "Catálogo Único de Claves Geoestadísticas / Marco Geoestadístico (wscatgeo v2)",
    "publisher": "INEGI",
    "url": "https://gaia.inegi.org.mx/wscatgeo/v2",
    "note": "Fuente: INEGI, Marco Geoestadístico. Simplified and re-coded by this project.",
}

# INEGI state code (cve_ent) -> ISO 3166-2 subdivision code (as used by reference_areas).
CVE_ENT_ISO = {
    "01": "MX-AGU", "02": "MX-BCN", "03": "MX-BCS", "04": "MX-CAM", "05": "MX-COA",
    "06": "MX-COL", "07": "MX-CHP", "08": "MX-CHH", "09": "MX-CMX", "10": "MX-DUR",
    "11": "MX-GUA", "12": "MX-GRO", "13": "MX-HID", "14": "MX-JAL", "15": "MX-MEX",
    "16": "MX-MIC", "17": "MX-MOR", "18": "MX-NAY", "19": "MX-NLE", "20": "MX-OAX",
    "21": "MX-PUE", "22": "MX-QUE", "23": "MX-ROO", "24": "MX-SLP", "25": "MX-SIN",
    "26": "MX-SON", "27": "MX-TAB", "28": "MX-TAM", "29": "MX-TLA", "30": "MX-VER",
    "31": "MX-YUC", "32": "MX-ZAC",
}  # fmt: skip


def raw_dir() -> Path:
    path = get_settings().raw_dir / "reference" / "inegi"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _fetch_json(client: PoliteClient, path: str, dest: Path) -> Any:
    """GET once; reuse the cached file on later runs (resumable download)."""
    if dest.is_file():
        return json.loads(dest.read_text(encoding="utf-8"))
    resp = client.get(f"{BASE}/{path}")
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(resp.content)
    tmp.rename(dest)
    return resp.json()


def download(client: PoliteClient | None = None) -> None:
    owns = client is None
    client = client or PoliteClient(min_interval=1.0, timeout=120)
    root = raw_dir()
    try:
        states = _fetch_json(client, "mgee/", root / "mgee.json")["datos"]
        for state in states:
            ent = state["cve_ent"]
            municipalities = _fetch_json(client, f"mgem/{ent}", root / f"mgem_{ent}.json")["datos"]
            _fetch_json(client, f"geo/mgem/{ent}", root / f"geo_mgem_{ent}.json")
            for i, mun in enumerate(municipalities, start=1):
                code = mun["cvegeo"]
                _fetch_json(client, f"localidades/{code}", root / "localidades" / f"{code}.json")
                if i % 50 == 0:
                    log.info("state %s: %d/%d municipalities", ent, i, len(municipalities))
            log.info(
                "state %s (%s) done: %d municipalities", ent, state["nomgeo"], len(municipalities)
            )
    finally:
        if owns:
            client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.reference.inegi")
    parser.add_argument("command", choices=["download", "load"])
    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)
    if args.command == "download":
        download()
    else:
        from app.reference.inegi_load import load  # noqa: PLC0415 — needs DB models

        load()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

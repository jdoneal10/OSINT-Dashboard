# Cartel OSINT Dashboard

> **UNCLASSIFIED — PUBLICLY AVAILABLE INFORMATION ONLY**

A local-first open-source intelligence workspace that tracks transnational criminal organization (TCO) activity from Central America to the U.S. Southwest Border. It collects, geolocates and analyzes **publicly available** reporting, and every record carries its source and a confidence score.

See [`PLAN.md`](PLAN.md) for the intelligence requirements and phase roadmap, and [`docs/`](docs/) for the architecture, data sources and decision records.

## Status

Phase 0 (foundation): repository, database, API/worker/web skeletons, local basemap, and cited reference data for the Phase 1 area of interest.

## Quick start (macOS, Apple Silicon)

Prerequisites: [OrbStack](https://orbstack.dev) (or any Docker engine), and the following from Homebrew: `uv`, `node`, `gitleaks` and `pmtiles`.

```bash
make setup     # install backend + frontend deps and the pre-commit hooks
make basemap   # one-time: extract the local PMTiles basemap (~few hundred MB)
make dev       # db + migrations + api + worker + web
make seed      # load cited reference data (AOI, USBP sectors, POEs, actors)
```

Open <http://localhost:5173>.

| Command | What it does |
|---|---|
| `make dev` | Start PostGIS (Docker), apply migrations, run api, worker and web |
| `make db-migrate` | `alembic upgrade head` |
| `make seed` | Load `data/reference/` into the database (idempotent) |
| `make test` | Backend (pytest) and frontend (Vitest) tests |
| `make lint` | ruff, mypy, eslint, prettier --check |
| `make ingest SOURCE=… SINCE=…` | Run one ingester manually (Phase 1+) |

## Data handling

- Publicly available information only. No classified, CUI, FOUO or LES material.
- Organizations, events and public legal actions only. No profiling of private individuals.
- No tracking of U.S. law-enforcement or military positions or tactics.
- Source terms are honored. ACLED data is never redistributed in raw form.

Map data © OpenStreetMap contributors, via [Protomaps](https://protomaps.com). Boundaries: Natural Earth (public domain), U.S. Census Bureau (public domain).

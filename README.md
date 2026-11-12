# Cartel OSINT Dashboard

> **UNCLASSIFIED — PUBLICLY AVAILABLE INFORMATION ONLY**

A local-first open-source intelligence workspace that tracks transnational criminal organization (TCO) activity from Central America to the U.S. Southwest Border. It collects, geolocates and analyzes **publicly available** reporting, and every record carries its source and a confidence score.

See [`PLAN.md`](PLAN.md) for the intelligence requirements and phase roadmap, and [`docs/`](docs/) for the architecture, data sources and decision records.

## Status

**Phase 2 (unstructured layer, all of Mexico):**
- News and press releases are ingested hourly and pass through a hybrid AI pipeline:
  - a local relevance filter (Ollama)
  - Claude Haiku for translation and extraction
  - Claude Sonnet for corroboration judgments
- Extracted events and seizures are geocoded against a local INEGI gazetteer, clustered across independent sources, and graded on the Admiralty scale.
- The app adds:
  - a news feed and document detail
  - an in-app labeling page for precision evaluation
  - OFAC and Federal Register designations
  - a SESNSP municipal crime choropleth
  - an LLM budget indicator

Phases 0 (foundation) and 1 (border MVP: ACLED and CBP) are complete.

## Quick start (macOS, Apple Silicon)

Prerequisites: [OrbStack](https://orbstack.dev) (or any Docker engine), and the following from Homebrew: `uv`, `node`, `gitleaks`, `pmtiles` and `ollama`. Then pull the local filter model with `ollama pull gemma3:4b`.

```bash
make setup     # install backend + frontend deps and the pre-commit hooks
make basemap   # one-time: extract the local PMTiles basemap (~few hundred MB)
make dev       # db + migrations + api + worker + web
make seed      # load cited reference data (AOI, USBP sectors, POEs, actors, feeds)
make reference-inegi   # one-time: INEGI municipalities + local gazetteer (~45 min)
```

API keys are kept in the macOS Keychain and never passed on the command line:

```bash
cd backend && uv run python -m app.core.secrets set ANTHROPIC_API_KEY
cd backend && uv run python -m app.enrich.llm.check   # verifies the key; never prints it
```

Open <http://localhost:5173>.

| Command | What it does |
|---|---|
| `make dev` | Start PostGIS (Docker), apply migrations, run api, worker and web |
| `make db-migrate` | `alembic upgrade head` |
| `make seed` | Load `data/reference/` into the database (idempotent) |
| `make test` | Backend (pytest) and frontend (Vitest) tests |
| `make lint` | ruff, mypy, eslint, prettier --check |
| `make ingest SOURCE=acled SINCE=2018-01-01` | ACLED backfill (incremental without `SINCE`; `DELETED=1` reconciles deletions) |
| `make ingest SOURCE=cbp ALL=1` | CBP files (`FILE=…` imports a manually downloaded file) |
| `make ingest SOURCE=news` | RSS, listing and GDELT feeds from `data/reference/feeds.yaml` (`FEED=slug` for one) |
| `make ingest SOURCE=designations` | OFAC SDN (regional programs) and Federal Register FTO/SDGT notices |
| `make ingest SOURCE=sesnsp FILE=…` | SESNSP municipal crime file (manual download; the site blocks automated access) |
| `make pipeline [STAGE=…]` | Enrichment pass: dedupe, local filter, Haiku extract, cluster/Admiralty, Sonnet analyze |
| `make eval [MODELS=…]` | Precision and filter-recall report from hand labels into `docs/evaluations/` |

The worker (started by `make dev`) runs the following on schedule:
- feeds hourly and GDELT every 3 hours
- the enrichment pipeline every 30 minutes
- designations daily
- ACLED daily, and CBP daily

The Claude stages stop when spend reaches 80% of the monthly cap ($75 by default).

## Data handling

- Publicly available information only. No classified, CUI, FOUO or LES material.
- Organizations, events and public legal actions only. No profiling of private individuals.
- No tracking of U.S. law-enforcement or military positions or tactics.
- Source terms are honored. ACLED data is never redistributed in raw form or used for profit; it is processed with Claude only under ACLED's written consent (ADR 0006).
- Only public article text is sent to the Claude API. Analyst labels and notes stay local.

Violence events: ACLED (Armed Conflict Location & Event Data), acleddata.com — used for non-profit professional analysis with ACLED's written consent; not redistributed. Border statistics: U.S. Customs and Border Protection public data; this project is not endorsed by CBP. Designations: U.S. Treasury OFAC and the Federal Register. Crime incidence: SESNSP (Secretariado Ejecutivo del Sistema Nacional de Seguridad Pública). Municipalities and gazetteer: INEGI Marco Geoestadístico. News discovery: the GDELT Project. Each news item links to its publisher.

Map data © OpenStreetMap contributors, via [Protomaps](https://protomaps.com). Boundaries: Natural Earth (public domain), U.S. Census Bureau (public domain).

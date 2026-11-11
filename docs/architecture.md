# Architecture

> UNCLASSIFIED — publicly available information only.

## Target pipeline (PLAN.md §5)

```
Ingestion (APScheduler worker)
  acled · cbp · gdelt · rss · fto/ofac · sesnsp · comtrade
        │  raw snapshots → data/raw/<source>/<date>/
        ▼
Enrichment pipeline
  local filter (MLX/Ollama) → Haiku extract + translate → geocode
  → actor normalization → dedupe/cluster → Sonnet escalation
  → Admiralty scoring
        ▼
PostgreSQL + PostGIS  ◄──►  FastAPI  ◄──►  React + MapLibre/deck.gl + ECharts
```

## Phase 0 runtime (as built)

```
 make dev
   ├─ docker compose ── PostGIS 16/3.5 ─────────── 127.0.0.1:5432  (osint, osint_test)
   ├─ alembic upgrade head
   └─ honcho (Procfile.dev)
        ├─ api     uvicorn app.main:app ────────── 127.0.0.1:8000
        ├─ worker  python -m app.worker (heartbeat → ingest_runs)
        └─ web     vite ───────────────────────── 127.0.0.1:5173
                     ├─ /api/*      → proxy to :8000
                     └─ /basemap/*  → data/basemap (PMTiles, fonts, sprites; Range-capable)
```

At runtime the browser talks only to `127.0.0.1:5173`. The basemap, glyphs and sprites are all local, so no third-party tile or font requests are made.

## Backend layout

| Path | Role |
|---|---|
| `app/core/config.py` | `pydantic-settings` (`OSINT_*` env vars, `.env`) |
| `app/core/secrets.py` | Keychain (`keyring`) → env → `.env` lookup, `SecretStr`, CLI to store keys |
| `app/core/logging.py` | Logging with a redaction filter for keys, tokens and DSN passwords |
| `app/db/models.py` | Core schema (PLAN.md §6). Provenance mixin, LLM-derivation mixin, CHECK-constrained enums, GiST indexes |
| `app/db/migrations/` | Alembic. `0001_baseline` is hand-reviewed autogenerate output |
| `app/api/` | `GET /health`, `GET /reference/aoi`, `GET /reference/nodes` |
| `app/reference/` | Validated, idempotent loader for `data/reference/` (citations required) |
| `app/worker.py` | Scheduler entrypoint (heartbeat only in Phase 0) |
| `app/ingest/` | One module per source from Phase 1. `python -m app.ingest` is the manual entrypoint |

## Data model notes

- **Upsert key:** every source-derived table has `UNIQUE(source_id, source_key)`, so re-running an ingester never duplicates rows.
- **Revisions:** `border_metrics` is keyed on `snapshot_date`. CBP revisions add rows and never overwrite earlier ones.
- **Individuals:** they have no table of their own. Names appear only as `designations.listed_parties`, attributes of public legal-action records (CLAUDE.md hard rule 3).
- **No public geometry:** nodes such as USBP sectors (ADR 0002) store `NULL` geometry. The API returns `geometry: null`, and the UI lists them instead of drawing them.

## Decisions

See [`decisions/`](decisions/): ADR 0001 (local runtime) and ADR 0002 (reference data).

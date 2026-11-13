# Architecture

> UNCLASSIFIED — open-source information only.

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

## Runtime (as built, Phase 2)

```
 make dev
   ├─ docker compose ── PostGIS 16/3.5 ─────────── 127.0.0.1:5432  (osint, osint_test)
   ├─ alembic upgrade head
   └─ honcho (Procfile.dev)
        ├─ api     uvicorn app.main:app ────────── 127.0.0.1:8000
        ├─ worker  python -m app.worker (APScheduler, UTC; see below)
        └─ web     vite ───────────────────────── 127.0.0.1:5173
                     ├─ /api/*      → proxy to :8000
                     └─ /basemap/*  → data/basemap (PMTiles, fonts, sprites; Range-capable)
```

At runtime the browser talks only to `127.0.0.1:5173`. The basemap, glyphs and sprites are all local, so no third-party tile or font requests are made. Ollama runs on `127.0.0.1:11434`.

Outbound calls go only to destinations listed in `docs/data-sources.md`: scheduled source pulls, the Claude API, and services an ADR approves (ADR 0008). Every source pull respects robots.txt and per-host rate limits.

### Worker schedule (UTC)

| Job | When | What |
|---|---|---|
| `heartbeat` | every 5 min | liveness row in `ingest_runs` (shown in `/health`) |
| `news-feeds` | hourly :05 | RSS and listing-page feeds |
| `news-gdelt` | every 3 h :20 | GDELT DOC queries for outlets without RSS |
| `pipeline` | :10 and :40 | dedupe → local filter → Haiku extract → cluster/Admiralty → Sonnet analyze |
| `acled-events` | daily 11:00 | ACLED incremental pull |
| `acled-deleted` | Sun 11:30 | ACLED deletion reconciliation |
| `cbp` | daily 12:00 | new CBP files only |
| `designations` | daily 13:00 | OFAC SDN (skipped when unchanged), Federal Register notices |
| `sesnsp-reminder` | 26th 14:00 | alert to download new SESNSP data when the newest snapshot is > 40 days old |

A failed job is logged and recorded, and does not stop the scheduler. The Claude gateway checks month-to-date spend before every call and pauses the API stages at 80% of the cap. The local filter and ingestion keep running while the API stages are paused.

### Enrichment pipeline (ADR 0004)

```
documents (new)
  → dedupe (canonical URL + SimHash; syndicated copies count once)
  → local filter: gemma3:4b via Ollama, threshold 0.2 (recall over precision; filter-v2)
  → Haiku extract (extract-v4): English summary, events, seizures, organizations;
      priority on human smuggling and border threats, with a border_threat category
      per event (ADR 0007; threat activity only, hard rule 4);
      strict JSON schema, one retry, then quarantine; no fields for people.
      A backlog of >= 25 documents (backfill, `make reextract`) goes out as one Message
      Batches job at 50% price; the `collect` stage stores results every 30 min
  → geocode against the local INEGI gazetteer / cited U.S. ports of entry; in_aoi flag
  → cluster (±1 day, 25 km, compatible type) + attach the matching ACLED event (ADR 0006)
  → Admiralty grade per cluster
  → Sonnet analyze (clusters with conflicting reports): ICD 203 judgment citing document
      and ACLED event ids
```

The single Claude gateway (`app/enrich/llm/client.py`) does the following:
- requires declared provenance for every call, and refuses ACLED-derived input unless ACLED's consent is on (ADR 0003, ADR 0006)
- enforces the budget
- uses prompt caching for the shared instruction block
- logs every call to `llm_usage` (batch results flagged and billed at 50%)

Sonnet stays real-time, because batch requests cannot use the server-side refusal fallback it relies on. The batch path (`app/enrich/llm/batch.py`) applies the same guards when it submits a batch:
- licence and provenance checks for every request
- the budget check, trimming the batch so its estimated cost stays under the pause threshold

Results are validated the same way as real-time responses. A failed result gets one real-time retry and is then quarantined.

## Backend layout

| Path | Role |
|---|---|
| `app/core/config.py` | `pydantic-settings` (`OSINT_*` env vars, `.env`) |
| `app/core/secrets.py` | Keychain (`keyring`) → env → `.env` lookup, `SecretStr`, CLI to store keys |
| `app/core/logging.py` | Logging with a redaction filter for keys, tokens and DSN passwords |
| `app/db/models.py` | Core schema (PLAN.md §6). Provenance mixin, LLM-derivation mixin, CHECK-constrained enums, GiST indexes |
| `app/db/migrations/` | Alembic. `0001_baseline` is hand-reviewed autogenerate output |
| `app/api/` | Health, reference layers (`/reference/aoi`, `/reference/municipalities`, `/reference/nodes`), `/events`, `/border`, `/actors`, `/documents`, `/clusters`, `/designations`, `/crime-incidence`, `/llm/usage`, `/labels` |
| `app/reference/` | Validated, idempotent loader for `data/reference/` (citations required) |
| `app/worker.py` | Scheduler entrypoint (schedule above) |
| `app/ingest/` | One module per source (`acled`, `cbp`, `news`, `designations`, `sesnsp`). `python -m app.ingest` is the manual entrypoint |
| `app/enrich/` | `local_filter`, `extract`, `geocode`, `dedupe`, `admiralty`, `analyze`, `actors`, `pipeline`, `evaluate`; `llm/` holds the Claude gateway, pricing and schema helpers |

## Data model notes

- **Upsert key:** every source-derived table has `UNIQUE(source_id, source_key)`, so re-running an ingester never duplicates rows.
- **Revisions:** `border_metrics` is keyed on `snapshot_date`. CBP revisions add rows and never overwrite earlier ones.
- **Individuals:** they have no table of their own. Names appear only as `designations.listed_parties`, attributes of public legal-action records, and, for leaders of criminal organizations identified as such by the source, in the free text of news-derived summaries, descriptions and evidence quotes (CLAUDE.md hard rule 3, ADR 0005).
- **No public geometry:** nodes such as USBP sectors (ADR 0002) store `NULL` geometry. The API returns `geometry: null`, and the UI lists them instead of drawing them.

## Decisions

See [`decisions/`](decisions/):
- ADR 0001: local runtime
- ADR 0002: reference data
- ADR 0003: Phase 1 ingest and the ACLED licence
- ADR 0004: Phase 2 sources and the AI pipeline
- ADR 0005: naming reported criminal-group leaders
- ADR 0006: ACLED written consent for Claude processing and professional use
- ADR 0007: priority focus on human smuggling and threats to the border

Evaluation reports are in [`evaluations/`](evaluations/).

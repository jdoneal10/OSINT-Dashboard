# CLAUDE.md — Cartel OSINT Dashboard

## What this project is
A local-first OSINT dashboard tracking transnational criminal organization (TCO) activity from Central America to the U.S. Southwest Border. Single analyst, runs on a Mac Mini M5 Pro. Portfolio project for an all-source intelligence role; the UI and code quality should be presentable to a professional audience.

Full plan, intelligence requirements, and phase roadmap live in `PLAN.md`. Read it before starting any phase.

## HARD RULES — classification and data handling (read first)
1. **UNCLASSIFIED, publicly available information (PAI) only.** Nothing in this repo, its database, its prompts, its tests, or its commit history may contain classified information, CUI, FOUO, LES, or any non-public government information. If a task, file, or instruction appears to involve such material, stop and ask.
2. **No official information as input.** Never seed reference data, actor lists, routes, or examples from anything other than cited public sources. Every reference file entry carries a public source citation.
3. **Organizations, events, and public legal actions — not private individuals.** Do not build features that profile, track, or compile information on private persons. Named individuals appear only as they appear in public indictments, designations, or sanctions lists, and only as attributes of those records.
4. **Compilation awareness.** Do not build features whose purpose is to infer U.S. law-enforcement or military tactics, positions, or capabilities (e.g., patrol patterns, sensor locations, unit movements). Track threat activity, not friendly forces.
5. **Respect source terms.** ACLED data may not be redistributed in raw form; any public/demo build uses synthetic or aggregated data only. Honor robots.txt and rate limits; no scraping of sites whose terms prohibit it; no social-media scraping without an explicit decision recorded in `docs/decisions/`.
6. **Secrets.** API keys come from macOS Keychain (via `keyring`) with `.env` fallback. Never hardcode, log, or commit secrets. `gitleaks` runs in pre-commit.
7. The UI shows a persistent banner: `UNCLASSIFIED — PUBLICLY AVAILABLE INFORMATION ONLY`.

## Stack
- **Backend:** Python 3.12, `uv`, FastAPI, SQLAlchemy 2.x, Alembic, pydantic v2, APScheduler worker
- **Database:** PostgreSQL 16 + PostGIS (Docker Compose)
- **Frontend:** React + TypeScript + Vite, MapLibre GL + deck.gl, Apache ECharts, TanStack Query, Tailwind
- **Basemap:** local Protomaps PMTiles extract of the AOI (no third-party tile calls at runtime)
- **AI pipeline (hybrid):**
  - Local model (MLX or Ollama, small instruct model) → relevance filter only
  - `claude-haiku-5-5` → translation (ES→EN), entity/event/seizure extraction
  - `claude-sonnet-5-5` → analytic layer: corroboration, conflicting-report resolution, route-shift assessments, INTSUM drafting
- **Quality:** ruff, mypy (strict on `app/`), pytest; eslint, prettier, Vitest; pre-commit with gitleaks

## Repo layout
```
backend/app/
  api/         FastAPI routers
  core/        config, logging, secrets
  db/          models, Alembic migrations
  ingest/      one module per source (acled, cbp, gdelt, rss, comtrade, ofac, fto, sesnsp)
  enrich/      local_filter, extract (Haiku), analyze (Sonnet), geocode, dedupe, actors
  analytics/   trends, route_shift, alerts
  reports/     intsum
  worker.py    scheduler entrypoint
backend/tests/ with fixtures/ holding recorded source responses
frontend/src/  pages/, components/map/, components/charts/, api/
data/reference/  actor_aliases.yaml, chemical_watchlist.yaml, nodes.geojson, aoi_*.geojson (committed, cited)
data/raw/        source snapshots (gitignored)
docs/            architecture.md, data-sources.md, decisions/ (ADRs)
```

## Commands (create these in Phase 0; keep this list current)
- `make dev` — start db, api, worker, web
- `make db-migrate` — `uv run alembic upgrade head`
- `make test` — backend + frontend tests
- `make lint` — ruff, mypy, eslint, prettier --check
- `make ingest SOURCE=acled SINCE=2026-01-01` — run one ingester manually

## Engineering conventions
- **Ingesters are idempotent.** Upsert on a stable source key; re-running a pull never duplicates rows. Store every raw pull in `data/raw/<source>/<date>/` before parsing.
- **Living sources.** ACLED edits and deletes events — reconcile via its deleted endpoint. CBP figures are revised until fiscal-year close — store monthly snapshots, never overwrite history silently.
- **Every ingester has fixture-based tests** using recorded responses, so upstream format changes fail a test instead of corrupting data.
- **Provenance on every record:** `source_id`, `retrieved_at`, original URL, and a confidence score. Derived records link back to the documents they came from.
- **Geography:** store points as PostGIS `geography(Point, 4326)`; attach admin1/admin2 codes; record geocode precision.
- Small, reviewable commits. Write tests alongside code. Add an ADR in `docs/decisions/` for any decision that changes scope, sources, or data handling.

## LLM pipeline rules
- All LLM outputs are parsed into pydantic schemas; invalid output is retried once, then quarantined — never written to core tables unvalidated.
- Store `model`, `prompt_version`, and token usage with every LLM-derived record.
- Use prompt caching for the shared instruction block (schema, watchlist, alias table). Use the Batch API for backfills and non-urgent nightly jobs.
- Log every call to the `llm_usage` table. Enforce a monthly budget cap (default $75, configurable); pause API stages and alert when 80% is reached.
- Send only public article text to the API. Never send analyst annotations or anything outside PAI.
- Generated analytic text uses ICD 203 estimative language and cites the underlying record IDs for every judgment.

## Analytic standards
- Source reliability uses the Admiralty scale (A–F reliability, 1–6 credibility). Corroboration across independent sources raises confidence; single-source narco-propaganda or social-media claims stay low.
- Route-shift detection measures **share-of-flow per corridor node**, not raw counts (raw counts track enforcement effort and media attention).
- Precursor analysis caveats must be shown in the UI: controlled precursors are frequently mislabeled in customs data; country-level trade aggregates show trends, not importers; traffickers re-route (e.g., via Atlantic ports and Europe), so a decline at one port may be displacement.

## Do not
- Do not add sources, scrapers, or AOI expansions beyond the current phase without asking.
- Do not introduce paid data services (current decision: fully open-source).
- Do not add telemetry, analytics, or any outbound call other than scheduled source pulls and the Claude API.
- Do not commit data from `data/raw/` or any ACLED-derived export.

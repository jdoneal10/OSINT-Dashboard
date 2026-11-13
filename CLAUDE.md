# CLAUDE.md — Cartel OSINT Dashboard

## What this project is
A local-first OSINT dashboard tracking transnational criminal organization (TCO) activity from Central America to the U.S. Southwest Border. Single analyst, runs on a Mac Mini M5 Pro. A personal analytic aid: it gives the owner an initial look before the owner's own analysis, and it decides nothing about anyone. It never ingests from, or substitutes for, official systems. The UI and code quality should stay presentable to a professional audience.

Full plan, intelligence requirements, and phase roadmap live in `PLAN.md`. Read it before starting any phase.

## HARD RULES — classification and data handling (read first)
1. **UNCLASSIFIED open-source information only, lawfully held on a personal system (ADR 0008).** Allowed inputs:
   - published sources;
   - account-based or licensed commercial data (including commercial imagery), used within its terms;
   - unpublished material the owner collects lawfully from open sources.

   Never classified information, CUI (including FOUO and LES), anything from a government system, or anything obtained through official duties. This applies to the repo, its database, its prompts, its tests and its commit history. If a task, file or instruction appears to involve such material, stop and ask.
2. **Cited reference data; the owner's judgment labeled as such.** Reference data (actor lists, aliases, routes, nodes, watchlists) is seeded only from cited open sources, and every entry carries its citation. The owner's analytic frameworks live in `docs/framework/`, labeled as owner judgment. They may shape prompts, PIRs and scoring, but are never stored or shown as sourced fact.
3. **People are recorded only as an open source links them to criminal activity (ADR 0008).** Person records, links and views are allowed for individuals an open source links to TCO activity: members, leaders, facilitators, operators, suppliers, owners of front businesses, and people named in indictments, designations, sanctions or prosecutions. Conditions:
   - **Cited:** every person attribute and link cites its source record and date, carries that source's Admiralty grade, and is shown as reported, never as established fact.
   - **Not recorded as persons:** victims, bystanders, witnesses, relatives not themselves reported as involved, journalists and minors. Officials are recorded only when a source reports them as complicit. Everyone else is described by role.
   - **No contact or personal-life details:** no home addresses, phone numbers, emails, ID or account numbers, health or family details. A front business's reported address is allowed.
   - **U.S. persons:** people or businesses reported as U.S. citizens, residents or U.S.-located are flagged `us_person` and excluded from person views and search by default (the owner's EO 12333 boundary).
   - **Owner control:** the owner can mark any person record disputed or delete it; deletion removes its links.
4. **Track threats, not friendly forces.** Do not build features whose purpose is to infer U.S. or partner law-enforcement or military tactics, positions or capabilities (patrol patterns, sensor or camera locations, unit movements, checkpoints, counter-UAS capabilities). TCO action against security forces (a drone attack, surveillance of an installation) is recorded as threat activity: a mission or target category plus the location at the source's precision. Never the units, positions or response.
5. **Respect source terms.**
   - **ACLED:** no raw redistribution and no profit. Under ACLED's written consent (ADR 0006), ACLED-derived views may be shown for professional, non-profit use with clear ACLED attribution, and ACLED data may be processed with Claude.
   - **All sources:** honor terms, robots.txt and rate limits; no scraping of sites whose terms prohibit it.
   - **ADR first:** social media, account-based sources, forums and paid data each need a decision in `docs/decisions/` that records the terms and how access works. The owner signs in to account-based sources; their credentials are never stored in the repo.
6. **Secrets.** API keys come from macOS Keychain (via `keyring`) with `.env` fallback. Never hardcode, log, or commit secrets. `gitleaks` runs in pre-commit.
7. The UI shows a persistent banner: `UNCLASSIFIED — OPEN-SOURCE INFORMATION ONLY`.

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
- `make setup` — install backend (uv) and frontend (npm) deps and the pre-commit hooks
- `make dev` — start db, api, worker, web (db in Docker; api/worker/web native via honcho; ADR 0001)
- `make seed` — load cited reference data from `data/reference/` (idempotent)
- `make basemap` — one-time local Protomaps extract into `data/basemap/` (gitignored, ~1.1 GB at z13)
- `make db-down` / `make db-reset` — stop PostGIS / destroy and recreate its volume (asks first)
- `make db-migrate` — `uv run alembic upgrade head`
- `make test` — backend + frontend tests
- `make lint` — ruff, mypy, eslint, prettier --check
- `make ingest SOURCE=acled SINCE=2018-01-01` — ACLED backfill (omit `SINCE` for an incremental pull; `DELETED=1` for deletion reconciliation)
- `make ingest SOURCE=cbp` — newest CBP files (`ALL=1` for every robots-allowed series; `FILE=path` to import a manually downloaded file)
- `make ingest SOURCE=news [FEED=slug]` — RSS/listing/GDELT feeds registered in `data/reference/feeds.yaml`
- `make ingest SOURCE=designations` — OFAC SDN (regional programs) and Federal Register FTO/SDGT notices
- `make ingest SOURCE=sesnsp FILE=path` — SESNSP municipal crime file (manual download; automated access is blocked)
- `make reference-inegi` — one-time INEGI municipalities + local gazetteer (resumable, ~45 min)
- `cd backend && uv run python -m app.core.secrets set ACLED_USERNAME` — store a secret in Keychain (owner runs this; never pass secrets on the command line)
- `cd backend && uv run python -m app.enrich.actors --rebuild` — re-run actor normalization over all events
- `cd backend && uv run python -m app.enrich.llm.check` — verify the stored Anthropic key (free Models API call; never prints the key)
- `make pipeline [STAGE=...]` — enrichment pass: dedupe, local filter, Haiku extract, cluster/Admiralty, Sonnet analyze
- `make reextract` — queue documents extracted under an older prompt version; the next pipeline run submits them as one Batch API job (50% price)
- `make eval [MODELS=qwen3:4b,gemma3:4b] [PROMPT=extract-v3]` — precision/filter-recall report from the owner's labels into `docs/evaluations/` (model comparison uses local Ollama only)

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
- Send only source content that hard rule 1 allows and whose terms permit AI processing (ACLED per ADR 0006). Never send analyst annotations.
- Generated analytic text uses ICD 203 estimative language and cites the underlying record IDs for every judgment.

## Analytic standards
- Source reliability uses the Admiralty scale (A–F reliability, 1–6 credibility). Corroboration across independent sources raises confidence; single-source narco-propaganda or social-media claims stay low.
- Route-shift detection measures **share-of-flow per corridor node**, not raw counts (raw counts track enforcement effort and media attention).
- Precursor analysis caveats must be shown in the UI: controlled precursors are frequently mislabeled in customs data; country-level trade aggregates show trends, not importers; traffickers re-route (e.g., via Atlantic ports and Europe), so a decline at one port may be displacement.

## Do not
- Do not add sources, scrapers, or AOI expansions beyond the current phase without asking.
- Do not introduce paid data services without an ADR (current decision: free sources only; the owner may revisit later).
- Do not add telemetry or analytics. Outbound calls go only to destinations listed in `docs/data-sources.md`: source pulls, the Claude API, and any service an ADR approves. A config allowlist enforcing the list is added with the first new destination (ADR 0008).
- Do not commit data from `data/raw/` or any ACLED-derived export.

# PLAN.md — Cartel OSINT Dashboard

**Owner:** Justin O'Neal
**Classification of this workspace:** UNCLASSIFIED — open-source information only
**Platform:** Mac Mini M5 Pro, local-first
**Last updated:** 2026-11-13

---

## 1. Purpose

A personal, unclassified OSINT workspace that collects, geolocates, and analyzes open-source reporting on transnational criminal organizations (TCOs) operating between Central America and the U.S. Southwest Border. It gives the owner an initial look before their own analysis. It complements, and never substitutes for or ingests from, official systems (ADR 0008).

**Audience:** the owner, for personal use. Code and UI stay presentable to a professional audience.

## 2. Intelligence requirements (IRs)

1. **Violence and activity.** Where is TCO violence occurring, by whom, and how is it trending?
2. **Territorial contestation.** Which groups are contesting which territory, and where are frontlines moving (e.g., Sinaloa Cartel internal conflict, CJNG expansion)?
3. **Border correlation.** How do events south of the border correlate with CBP encounter and seizure trends by sector and port of entry?
4. **Foreign precursor movement.** Which precursor and essential chemicals are entering Mexico, through which ports, from which origin countries, and how are those patterns changing?
5. **Smuggling route shifts.** How are drugs, people, and precursors moving along land, maritime, and air corridors, and when does flow measurably shift away from established routes?
6. **U.S. legal and policy actions.** What FTO designations, OFAC sanctions, and DOJ indictments target these groups, and when?
7. **Indications and warning.** What new indicators should trigger an alert?
8. **Unmanned systems (top priority).** Which cartels use drones, UGVs and USVs, for what missions, acquired and adapted how, and is their use escalating (from camera drones to FPV and weaponized systems, coordinated operations)? Seven PIRs are listed in `docs/framework/uxs-and-electricity-theft.md` §1 (ADR 0009).
9. **Electricity theft (top priority).** Which criminal organizations and facilitators steal electricity, by what methods, to power what (crypto mining, cultivation, labs, storage), where and at what scale? Seven PIRs are listed in framework §2 (ADR 0009).

Priority tiers (ADR 0009): IRs 8 and 9 first; human smuggling and border threats (ADR 0007) second; all other IRs third.

IRs 4 and 5 form one supply chain (ports → labs → corridors → crossings) and are modeled as a connected graph.

## 3. Area of interest by phase

| Phase | AOI |
|---|---|
| 1 | U.S.–Mexico border: 6 Mexican border states (BC, SON, CHIH, COAH, NL, TAMPS), 4 U.S. border states, 9 USBP sectors, SW land ports of entry |
| 2–4 | All of Mexico, including interior production regions (Sinaloa, Jalisco, Michoacán, Guerrero) and seaports (Manzanillo, Lázaro Cárdenas, Veracruz, others) |
| 5 | Central American transit corridor (GT, BZ, HN, SV, NI, CR, PA) and Eastern Pacific / Caribbean maritime approaches |

## 4. Data sources (open source; ADR 0008)

| Source | Use | IRs | Phase | Access notes |
|---|---|---|---|---|
| ACLED | Geocoded violence events with named actors (MX/CA coverage from 2018) | 1, 2, 3, 7 | 1 | Free myACLED account; OAuth for API; living dataset (reconcile deletions); no raw redistribution |
| CBP Public Data Portal | SW border encounters; drug seizures by AOR | 3, 5 | 1 | Free CSV; figures revised until FY close — snapshot monthly |
| GDELT 2.0 DOC/GEO API | Multilingual news discovery | 1, 2, 4, 5 | 2 | Free, no key; noisy — local filter first |
| RSS / press releases | InSight Crime, Border Report, CTC Sentinel, CRS, Mexican outlets, DOJ, DEA, USCG, SEMAR, FGR | All | 2 | Free; honor robots.txt and rate limits |
| State Dept FTO list, OFAC SDN list | Designations and sanctions | 6 | 2 | Free; SDN available as XML/CSV |
| SESNSP | Mexican municipal crime incidence | 1, 2 | 2 | Free downloads |
| Official bulletins: CFE, FGR, Guardia Nacional, SEDENA, SEMAR; Mexican energy press; drone and defense trade press | UxS and electricity-theft cases, seizures, prosecutions | 8, 9 | 3 | RSS or listing pages; terms check and ADR each |
| Pixtoday.net | Open-source aggregation | 8, 9 | 3 | Owner's account; terms check and ADR before automated use |
| Telegram public channels | Cartel-published claims and footage descriptions | 8, 9, 1 | 3 | Official API, text only, low Admiralty grade; ADR first |
| Search API (e.g. Brave) | Framework taxonomy queries | 8, 9 | 3 | Sanctioned API in place of search-engine scraping; ADR first |
| UN Comtrade | Monthly Mexico imports by HS code and partner (precursors; drones and mining hardware) | 4, 8, 9 | 4 | Free tier with registration |
| DEA Special Surveillance List, INCB precursor tables, InSight Crime precursor research | Build the chemical watchlist and HS mapping | 4 | 4 | Reference only |
| USCG / JIATF-South releases, Central American press | Maritime interdictions, CA seizures | 5 | 5 | Free |
| AIS, Sentinel-2, owner's commercial imagery account | Port calls, imagery supporting reported cases | 4, 5, 8, 9 | 6 (optional) | Licence terms recorded in an ADR first |

Paid trade data (Panjiva, ImportGenius, Sayari, Altana) is out of scope for now. The owner may revisit it later through an ADR (ADR 0008), and the schema leaves a slot for it.

## 5. Architecture

```
Ingestion (APScheduler worker)
  acled · cbp · gdelt · rss · fto/ofac · sesnsp · comtrade
        │  raw snapshots → data/raw/
        ▼
Enrichment pipeline
  local filter (MLX/Ollama) → Haiku 5.5 extract + translate → geocode
  → actor normalization → dedupe/cluster → Sonnet 5.5 escalation
  → Admiralty scoring
        ▼
PostgreSQL + PostGIS  ◄──►  FastAPI  ◄──►  React + MapLibre/deck.gl + ECharts
```

## 6. Data model (core tables)

- `sources` — name, type, Admiralty reliability, license/terms notes
- `documents` — raw article/report, original language text, translation, URL, retrieved_at
- `events` — date, geography point, admin1/admin2, event type, fatalities, confidence, source links
- `actors` + `actor_aliases` — canonical TCO records and every known alias/spelling
- `actor_events` — actor ↔ event with role (perpetrator, target, other)
- `seizures` — date, node, substance, chemical class, quantity + unit, seizing agency, country, source, confidence
- `chemical_watchlist` — name, aliases, CAS, HS code, control status, role (precursor / pre-precursor / essential)
- `trade_flows` — Comtrade aggregates by reporter, partner, HS code, month
- `border_metrics` — CBP encounters and seizures by sector/POE, month, snapshot date
- `designations` — FTO, SDN, indictment actions with dates and linked actors
- `nodes` / `edges` — corridor graph (ports, crossings, lab regions, transit hubs; mode per edge)
- `alerts` — rule, trigger time, linked records, status
- `annotations` — analyst notes on any record
- `llm_usage` — model, prompt version, tokens, cost, timestamp

## 7. AI enrichment pipeline

| Stage | Engine | Job |
|---|---|---|
| Relevance filter | Local model (MLX/Ollama) | Drop off-topic GDELT/RSS hits before any API spend |
| Extraction + translation | `claude-haiku-5-5` | ES→EN summary, structured events, actors, locations, seizures, chemicals |
| Analytic layer | `claude-sonnet-5-5` | Resolve conflicting reports, corroboration judgments, route-shift assessments, INTSUM drafts |

**Cost estimate (Nov 2026 pricing):** ~$50/month typical, ~$170/month heavy, ~$50 one-time backfill via Batch API. Budget cap enforced in `llm_usage` (default $75/month). Check whether subscription API credits apply.

**Controls:** pydantic-validated outputs, quarantine on failure, prompt caching on the shared instruction block, Batch API for non-urgent work, model and prompt version stored on every derived record.

## 8. Dashboard views

1. **Operational map** — events (heat + points), time slider, actor and event-type filters, USBP sector and POE overlays
2. **Border panel** — encounters and seizures by sector/POE vs. violence in adjacent Mexican states
3. **News feed** — translated, deduplicated reporting with Admiralty ratings; original text one click away
4. **Actor profiles** — area of activity over time, rivals/allies, designations and indictments timeline
5. **Precursor panel** — Comtrade trends for watchlist HS codes by origin, port seizure timeline, origin → port flow map, caveats displayed
6. **Route view** — corridor graph map (edge weight = volume, color = change), Sankey, route-shift alerts
7. **Alerts** — spike detection, new actor names, new designations, route shifts
8. **INTSUM export** — draft summary for a selected window and AOI, every judgment linked to source records
9. **UxS panel** — map and trend of reported drone, UGV and USV activity by platform, mission and actor; escalation-ladder view; procurement and training reporting
10. **Electricity-theft panel** — reported cases by method, powered activity and facilitator; map and trend; no suspect-site inference
11. **Person view** — people as open sources link them to TCO activity, every attribute cited and graded; U.S. persons hidden by default (ADR 0008)

## 9. Phased roadmap

### Phase 0 — Foundation (~1 week)
- Repo, pre-commit (ruff, mypy, eslint, prettier, gitleaks), Makefile, GitHub Actions (private repo)
- Docker Compose with PostgreSQL 16 + PostGIS; Alembic baseline schema
- FastAPI skeleton with health check; config via pydantic-settings; secrets via `keyring`
- React + TS + Vite skeleton; MapLibre with local PMTiles basemap; classification banner
- Reference data: Phase 1 AOI GeoJSON, USBP sectors and POEs as `nodes`, seed `actor_aliases.yaml` (all entries cited)
- `docs/data-sources.md` with terms of use for each source

**Exit criteria:** `make dev` brings up db, api, worker, and web; the map renders the Phase 1 AOI; CI passes.

### Phase 1 — Border MVP (2–3 weeks)
- ACLED ingester: OAuth, incremental pulls, upsert, deleted-endpoint reconciliation, AOI filter
- CBP ingester: SW encounters + drug seizures, monthly snapshots
- Rule-based actor normalization v1
- API: `/events`, `/events/geojson`, `/border/metrics`, `/seizures`, `/actors`
- Views: operational map, border panel; ACLED attribution in UI

**Exit criteria:** border-state ACLED events 2018–present on the map; CBP data FY20–present in the border panel; ingesters idempotent with fixture tests.

### Phase 2 — Unstructured layer + all of Mexico (~3 weeks)
- AOI expands to all of Mexico
- GDELT and RSS ingesters; SESNSP; FTO and OFAC SDN designations tracker
- Full hybrid AI pipeline with budget cap and usage ledger
- Geocoding, dedupe/clustering, Admiralty scoring
- News feed and document detail views

**Exit criteria:** pipeline runs unattended daily; extraction precision ≥ 85% on a 100-article hand-labeled test set; spend inside budget.

### Phase 3 — Unmanned systems, electricity theft and people (~3–4 weeks; ADR 0009)
- Sources: research and ADR each of official bulletins, Pixtoday.net, Telegram public channels and a search API; outbound allowlist enforced in config
- Prompts `filter-v3` and `extract-v6` with the tiered priority; UxS fields (platform, mission, payload, activity) and an `energy_theft` event type (method, powered activity, facilitator, reported scale) from the owner framework
- Person records under ADR 0008: `persons`, person–organization and person–event links, every attribute cited and graded, `us_person` flag hidden by default, dispute/delete
- Views: UxS and electricity-theft panels (map, trend, escalation ladder), person view, labeling fields for the new categories and the person safeguards
- Re-extraction through the Batch API

**Exit criteria:** IRs 8 and 9 answerable from the dashboard with cited records; ≥ 85% precision on the new fields over a labeled UxS/energy sample; zero labeled person-safeguard violations (contact details, victims or journalists recorded as persons, uncited attributes).

### Phase 4 — Precursors and routes (~3 weeks)
- `chemical_watchlist.yaml` with HS-code mapping (DEA SSL, INCB, InSight Crime)
- Comtrade ingester; seizure extraction from SEMAR/FGR/ANAM/Guardia Nacional reporting
- Corridor graph (`nodes`/`edges`); route-shift detection on share-of-flow with change-point methods
- Precursor panel and route view, with caveats shown in the UI

**Exit criteria:** IR 4 and IR 5 answerable from the dashboard with documented confidence and caveats.

### Phase 5 — Central America + analysis and alerts (2–3 weeks)
- AOI expands to Central America and maritime approaches; USCG/JIATF-South interdictions
- Actor profiles; alert rules with local macOS notifications
- INTSUM export using ICD 203 estimative language with record-level citations

**Exit criteria:** a weekly INTSUM is generated where every judgment traces to source records.

### Phase 6 — Polish and expansion (ongoing)
- Public demo mode on synthetic or aggregated data (no raw ACLED)
- README with screenshots, architecture write-up, short case study
- Optional, with an ADR for each: AIS port calls, Sentinel-2 imagery, social media

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Classification spillage or compilation sensitivity | CLAUDE.md hard rules; unclassified open-source inputs only, never CUI or government-system data; no friendly-force tracking; review the project with the security office and ethics counselor before any public release |
| Noisy or manipulated reporting (narco-propaganda, recycled claims) | Admiralty scoring, corroboration logic, confidence shown on every record |
| ACLED licensing | Private build only uses raw data; public demo uses synthetic or aggregated data |
| Mexican government data opacity on ports | Combine Comtrade aggregates with seizure reporting; state the gaps explicitly in the UI |
| Precursor mislabeling and re-routing | Watch essential chemicals as well as controlled precursors; monitor Atlantic ports and transshipment points; display caveats |
| GDELT noise drives API cost | Local filter first; budget cap; Batch API |
| Misattribution of named people | Person attributes only as an open source reports them, each cited and Admiralty-graded and shown as "reported"; no contact details; U.S. persons excluded from person views by default; owner can dispute or delete (ADR 0008) |
| Scope creep | Phase gates with exit criteria; ADRs for any expansion |

## 11. Decisions log

| # | Decision | Date |
|---|---|---|
| 1 | Portfolio project; UNCLASSIFIED PAI workspace that complements classified work | 2026-11-11 |
| 2 | Full React + FastAPI build | 2026-11-11 |
| 3 | Hybrid AI: local filter, Haiku 5.5 extraction/translation, Sonnet 5.5 analysis | 2026-11-11 |
| 4 | Phase 1 AOI limited to the U.S.–Mexico border | 2026-11-11 |
| 5 | Fully open-source data; no paid trade data for now | 2026-11-11 |
| 6 | IRs 4 (precursors) and 5 (route shifts) added | 2026-11-11 |
| 7 | Hard rules revised: open-source (not only published) inputs; people linked to criminal activity may be recorded with safeguards; outbound calls by allowlist; paid data by ADR. Supersedes decisions 1 and 5 (ADR 0008) | 2026-11-13 |
| 8 | UxS and electricity theft are top priority; Phase 3 becomes UxS, electricity theft and people; later phases shift by one (ADR 0009) | 2026-11-13 |

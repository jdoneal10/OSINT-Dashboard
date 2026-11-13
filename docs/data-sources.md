# Data sources and terms of use

> UNCLASSIFIED — OPEN-SOURCE INFORMATION ONLY. Every source here is open source and free; paid data needs its own ADR (ADR 0008).

**Rules that apply to every source (CLAUDE.md):**
- Store every raw pull under `data/raw/<source>/<date>/`, which is gitignored and never committed.
- Honor robots.txt and published rate limits.
- No scraping where the terms prohibit it.
- No social-media collection without an ADR.

Before writing a source's ingester, re-read its current terms and update this file (who checked, and when). Rows marked **to verify** have not been checked against the live terms yet.

## Ingest sources

| Source | Phase | Access | Key terms and handling | Terms status |
|---|---|---|---|---|
| **ACLED** | 1 | myACLED account (API tier); OAuth password grant; `/api/acled/read`, `/api/deleted/read` | Personal non-commercial licence (EULA eff. 2026-11-01). Internal use only; **no raw redistribution**; external material must be transformative and not reverse-engineerable (demo/screenshots use synthetic or aggregated data). **No ACLED content as LLM input** without written consent (s.7.1). API only, no scraping; rate limits not published. Attribute on every visual: "ACLED (Armed Conflict Location & Event Data)", link, access date, filters. Keep usage records 3 years (s.15). Living dataset: weekly deleted-events reconciliation. See ADR 0003. | Checked 2026-11-11 (EULA, Content Usage, Attribution Policy, API docs) |
| **CBP Public Data Portal** (SW border encounters, drug seizures) | 1 | CSV files listed on `cbp.gov/document/stats/*` (no API) | U.S. government data. Terms: cite retrieval date; state the product uses CBP data but is **not endorsed by CBP**; no CBP/DHS logos. robots.txt disallows `/sites/default/files/assets/documents/` (FY20–FY23 files) — never fetched; imported manually. Revised until FY close: each file is a new `snapshot_date`, never overwritten. See ADR 0003. | Checked 2026-11-11 (terms page, robots.txt, document pages) |
| **GDELT 2.0 DOC API** | 2 | No key | Free for any academic, commercial or governmental use; cite GDELT and link gdeltproject.org. Discovery layer for outlets without RSS (Proceso, Milenio); local relevance filter before any API spend. | Checked 2026-11-11 (about page; live query) |
| **RSS / press releases** (see `data/reference/feeds.yaml`) | 2 | RSS, listing pages, GDELT discovery | Full text from outlets whose robots.txt permits our client, as private non-commercial research — **including Proceso and Milenio, whose terms prohibit reproduction (owner-accepted risk, ADR 0004)**. Excluded: outlets blocking AI agents (Border Report, El Siglo de Torreón, CRS) or disallowing our client (El Universal, El Diario de Juárez), and DEA/USCG (robots.txt 403). Per-outlet terms recorded in `feeds.yaml`. Never redistributed. | Checked 2026-11-11 (robots.txt all; terms: Proceso, Milenio, Ríodoce, InSight Crime) |
| **State Dept FTO list; Federal Register** | 1–2 | Federal Register API (`/api/v1/documents.json`, no key) | U.S. government work; the citable record for designations. state.gov refuses automated fetches. Since 2025-02-20: Cartel de los Soles (2025-11-24, FR 2025-20750) and Juárez Cartel + Los Viagras (2026-07-16, FR 2026-14259). | Checked 2026-11-11 (live API query) |
| **OFAC SDN list** | 2 | Public XML export (`sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN_ADVANCED.XML`) | U.S. government data. Filter to narcotics/TCO/SDGT programs with a Mexico or Central America nexus. Individuals appear only as attributes of designation records (hard rule 3). | Checked 2026-11-11 (endpoint responds) |
| **SESNSP** (Mexican municipal crime incidence) | 2 | Downloads hosted on SharePoint (gob.mx/sesnsp datos abiertos) | No licence stated on the page; accuracy is the reporting agency's responsibility. **Methodology break in 2026** — store 2015–2025 and 2026+ series separately. Automated download to verify; manual import fallback. | Checked 2026-11-11 (download page) |
| **gob.mx press: Guardia Nacional, Defensa, SSPC** | 3 (proposed) | Listing pages `gob.mx/<agency>/es/archivo/prensa` | gob.mx terms: personal non-commercial use; no public display, redistribution or transfer. robots.txt has no `*` group. Same handling as SEMAR/FGR. ADR 0010. | Checked 2026-11-13 (robots.txt, terms) |
| **CFE bulletins** | — | `app.cfe.mx` bulletin app | Behind bot protection: not automated. CFE cases come via press and GDELT. ADR 0010. | Checked 2026-11-13 |
| **The War Zone, DroneDJ, El Economista** | 3 (proposed) | RSS | robots.txt allows (TWZ declares `ai-input=yes`). **Terms to verify** per feed before activation. Energía a Debate excluded (blocks Claude agents and feeds). ADR 0010. | robots.txt checked 2026-11-13 |
| **Pixtoday.net** | 3 (pending) | Owner's account | robots.txt `Disallow: /`; 403 to automated fetches. Owner file import or written permission only, after the owner reads its terms. ADR 0010. | Terms unread (sign-in needed) |
| **Telegram** | — | — | **Excluded:** API Terms §1.5 and content-licensing terms prohibit AI use of platform data. ADR 0010. | Checked 2026-11-13 |
| **Brave Search API** | — | — | **Deferred:** ToS §3(b)(i) forbids storing results without a paid storage plan. GDELT taxonomy queries used instead. ADR 0010. | Checked 2026-11-13 |
| **UN Comtrade** | 4 | Free tier with registration | Check call limits and redistribution terms for the free tier. Country-level aggregates show trends, not importers (caveat shown in the UI). | To verify before Phase 4 |
| **DEA SSL, INCB precursor tables, InSight Crime precursor research** | 4 | Public documents | Reference only, for `chemical_watchlist.yaml` with a citation per entry. | To verify before Phase 4 |
| **USCG / JIATF-South releases, Central American press** | 5 | Public | As for RSS / press releases. | To verify before Phase 5 |
| **AIS, Sentinel-2, owner's commercial imagery** | 6 (optional) | Free tiers | Needs an ADR before any use. | — |

## Reference and basemap sources (Phase 0)

| Source | Used for | License / attribution | Checked |
|---|---|---|---|
| [Natural Earth 1:10m admin-1](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-1-states-provinces/) | Phase 1 AOI state polygons | Public domain | 2026-11-11 |
| [BTS Border Crossing Entry Data (keg4-3bc2)](https://data.bts.gov/Research-and-Statistics/Border-Crossing-Entry-Data/keg4-3bc2) | SW land port-of-entry points | U.S. government work (BTS, from CBP) | 2026-11-11 |
| [CBP Border Patrol sector pages](https://www.cbp.gov/border-security/along-us-borders/border-patrol-sectors) | USBP sector names and citations (no geometry, ADR 0002) | U.S. government work | 2026-11-11 |
| [Federal Register 90 FR 10030](https://www.govinfo.gov/content/pkg/FR-2025-02-20/html/2025-02873.htm) | Seed actors and aliases | U.S. government work | 2026-11-11 |
| [INEGI free-use terms](https://www.inegi.org.mx/inegi/terminos.html) | Municipalities and localities gazetteer (Phase 2) | Reuse, modification and commercial use allowed; attribute "Fuente: INEGI, <product>"; disclose transformations; never imply INEGI endorsement | 2026-11-11 |
| [Protomaps daily build](https://docs.protomaps.com/basemaps/downloads) | Local PMTiles basemap | OpenStreetMap data © OSM contributors, **ODbL**; attribution shown on the map | 2026-11-11 |
| [protomaps/basemaps-assets](https://github.com/protomaps/basemaps-assets) | Glyphs and sprites | Noto fonts under the SIL Open Font License | 2026-11-11 |

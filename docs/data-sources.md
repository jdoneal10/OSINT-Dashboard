# Data sources and terms of use

> UNCLASSIFIED — publicly available information only. Every source here is public and free (PLAN.md decision 5: no paid data).

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
| **GDELT 2.0 DOC/GEO API** | 2 | No key | Open use with citation. High-noise discovery feed: local relevance filter before any API spend. Respect rate guidance. | To verify before Phase 2 |
| **RSS / press releases** (InSight Crime, Border Report, CTC Sentinel, CRS, Mexican outlets, DOJ, DEA, USCG, SEMAR, FGR) | 2 | Public feeds | Per-outlet copyright: store the URL, metadata and article text for local analysis only, and never republish full text. Check each outlet's robots.txt and feed terms before adding it. U.S. agency releases are public domain. | To verify per outlet |
| **State Dept FTO list; Federal Register** | 1–2 | Public | U.S. government work. The Federal Register (govinfo.gov / federalregister.gov) is the citable record. state.gov refuses automated fetches, so use the Federal Register instead. | FR checked 2026-11-11 |
| **OFAC SDN list** | 2 | Public XML/CSV | U.S. government work. Individuals appear only as attributes of designation records (hard rule 3). | To verify before Phase 2 |
| **SESNSP** (Mexican municipal crime incidence) | 2 | Public downloads | Mexican government open data. Check the license terms and attribution text. | To verify before Phase 2 |
| **UN Comtrade** | 3 | Free tier with registration | Check call limits and redistribution terms for the free tier. Country-level aggregates show trends, not importers (caveat shown in the UI). | To verify before Phase 3 |
| **DEA SSL, INCB precursor tables, InSight Crime precursor research** | 3 | Public documents | Reference only, for `chemical_watchlist.yaml` with a citation per entry. | To verify before Phase 3 |
| **USCG / JIATF-South releases, Central American press** | 4 | Public | As for RSS / press releases. | To verify before Phase 4 |
| **AIS, Sentinel-2** | 5 (optional) | Free tiers | Needs an ADR before any use. | — |

## Reference and basemap sources (Phase 0)

| Source | Used for | License / attribution | Checked |
|---|---|---|---|
| [Natural Earth 1:10m admin-1](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-1-states-provinces/) | Phase 1 AOI state polygons | Public domain | 2026-11-11 |
| [BTS Border Crossing Entry Data (keg4-3bc2)](https://data.bts.gov/Research-and-Statistics/Border-Crossing-Entry-Data/keg4-3bc2) | SW land port-of-entry points | U.S. government work (BTS, from CBP) | 2026-11-11 |
| [CBP Border Patrol sector pages](https://www.cbp.gov/border-security/along-us-borders/border-patrol-sectors) | USBP sector names and citations (no geometry, ADR 0002) | U.S. government work | 2026-11-11 |
| [Federal Register 90 FR 10030](https://www.govinfo.gov/content/pkg/FR-2025-02-20/html/2025-02873.htm) | Seed actors and aliases | U.S. government work | 2026-11-11 |
| [Protomaps daily build](https://docs.protomaps.com/basemaps/downloads) | Local PMTiles basemap | OpenStreetMap data © OSM contributors, **ODbL**; attribution shown on the map | 2026-11-11 |
| [protomaps/basemaps-assets](https://github.com/protomaps/basemaps-assets) | Glyphs and sprites | Noto fonts under the SIL Open Font License | 2026-11-11 |
